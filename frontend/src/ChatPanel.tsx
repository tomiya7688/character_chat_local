import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import Markdown from 'react-markdown';
import { ApiClient, ApiError, errorMessage } from './api';
import type { ChatResult, ChatStreamEvent, GenerationPhase, Message, Summary } from './types';

type WindowRequest = { tail?: boolean; before?: number; after?: number };

export function ChatPanel({ api, conversationId, name, provider, model, temperature, onBusy, onBranchCreated }: {
  api: ApiClient; conversationId: string; name: string; provider: string; model: string;
  temperature: number; onBusy: (busy: boolean) => void; onBranchCreated: (conversationId: string) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [preview, setPreview] = useState('');
  const [generationId, setGenerationId] = useState<string | null>(null);
  const [generationConversationId, setGenerationConversationId] = useState<string | null>(null);
  const [phase, setPhase] = useState<GenerationPhase | 'stopping'>('generating');
  const [editTarget, setEditTarget] = useState<Message | null>(null);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [latest, setLatest] = useState(true);
  const [hasOlder, setHasOlder] = useState(false);
  const [result, setResult] = useState<ChatResult | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryError, setSummaryError] = useState('');
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [focusMessage, setFocusMessage] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const summaryRequestRef = useRef<AbortController | null>(null);
  const sendLock = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async (params: WindowRequest = { tail: true }) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    try {
      const data = await api.messages(conversationId, params, controller.signal);
      if (controller.signal.aborted) return;
      if (!data.length && !params.tail) {
        if (params.before) setHasOlder(false);
        else setLatest(true);
        return;
      }
      setMessages(data);
      setHasOlder(data.length === 100 || params.after !== undefined);
      setLatest(Boolean(params.tail) || (params.after !== undefined && data.length < 100));
      setUncertain(false);
      setError('');
    } catch (e) {
      if (controller.signal.aborted) return;
      throw e;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [api, conversationId]);

  const loadSummary = useCallback(async () => {
    summaryRequestRef.current?.abort();
    const controller = new AbortController();
    summaryRequestRef.current = controller;
    setSummaryLoading(true); setSummaryError('');
    try {
      const data = await api.summary(conversationId, controller.signal);
      if (!controller.signal.aborted) setSummary(data);
    } catch (e) {
      if (!controller.signal.aborted) setSummaryError(errorMessage(e));
    } finally {
      if (!controller.signal.aborted) setSummaryLoading(false);
    }
  }, [api, conversationId]);

  useEffect(() => {
    void load().catch(e => setError(errorMessage(e)));
    return () => { requestRef.current?.abort(); summaryRequestRef.current?.abort(); };
  }, [load]);
  useEffect(() => { if (summaryOpen) void loadSummary(); }, [summaryOpen, loadSummary]);
  useEffect(() => {
    if (loading) return;
    if (focusMessage) document.getElementById(`message-${focusMessage}`)?.scrollIntoView({ block: 'center' });
    else if (latest) endRef.current?.scrollIntoView({ block: 'nearest' });
  }, [messages, latest, loading, focusMessage]);

  async function consumeStream(stream: AsyncGenerator<ChatStreamEvent>) {
    sendLock.current = true;
    setSending(true); onBusy(true); setError(''); setResult(null);
    setPreview(''); setGenerationId(null); setGenerationConversationId(null); setPhase('generating');
    let committed = false;
    let stopped = false;
    try {
      let accepted: ChatResult | null = null;
      for await (const streamEvent of stream) {
        if (streamEvent.type === 'started') {
          setGenerationId(streamEvent.generation_id);
          setGenerationConversationId(streamEvent.conversation_id);
        } else if (streamEvent.type === 'draft_delta') setPreview(current => current + streamEvent.text);
        else if (streamEvent.type === 'phase') setPhase(streamEvent.phase);
        else if (streamEvent.type === 'final') accepted = streamEvent.result;
        else if (streamEvent.type === 'stopped') {
          stopped = true;
          setPreview('');
          setError('生成を停止しました。元の会話は変更されていません。');
        } else if (streamEvent.type === 'error') {
          const status = streamEvent.code === 'quality_rejected' || streamEvent.code === 'invalid_request'
            ? 422 : streamEvent.code === 'conversation_conflict' ? 409
              : streamEvent.code === 'provider_error' ? 502 : 500;
          const message = streamEvent.code === 'quality_rejected'
            ? '品質チェックを通過する応答が得られませんでした。元の会話は変更されていません。'
            : streamEvent.code === 'provider_error'
              ? 'モデルへの接続に失敗しました。元の会話は変更されていません。'
              : streamEvent.code === 'conversation_conflict'
                ? '会話が別の更新と競合しました。履歴を再読込してからやり直してください。'
                : streamEvent.code === 'invalid_request'
                  ? '入力または設定が上限を超えています。文字数やキャラクター設定を確認してください。'
                  : '生成に失敗しました。履歴を再読込して保存状況を確認してください。';
          throw new ApiError(message, status, streamEvent.code);
        }
      }
      if (stopped) return;
      if (!accepted || !accepted.guardian.passed || !accepted.text.trim()) {
        throw new ApiError('応答の検証結果を確認できませんでした。履歴を再読込してください。', 0);
      }
      committed = true;
      setDraft(''); setEditTarget(null); setPreview(''); setResult(accepted); setFocusMessage(null);
      if (accepted.conversation_id !== conversationId) {
        onBranchCreated(accepted.conversation_id);
      } else {
        await load();
        if (summaryOpen) await loadSummary();
      }
    } catch (e) {
      setPreview('');
      setError(committed
        ? '応答は保存されましたが、履歴を取得できませんでした。再送せず一覧を更新してください。'
        : errorMessage(e));
      if (!committed && e instanceof ApiError && (e.status === 0 || e.status >= 500 || e.status === 409)) setUncertain(true);
    } finally {
      sendLock.current = false; setSending(false); setGenerationId(null); setGenerationConversationId(null);
      onBusy(false); inputRef.current?.focus();
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const input = draft.trim();
    if (sendLock.current || loading || uncertain || !input || !model.trim() || !provider) return;
    const stream = editTarget
      ? api.editRetryStream(conversationId, editTarget.id, provider, model.trim(), input, temperature)
      : api.chatStream(conversationId, provider, model.trim(), input, temperature);
    await consumeStream(stream);
  }

  async function regenerate(message: Message) {
    if (sendLock.current || loading || uncertain || draft.trim() || editTarget || !model.trim() || !provider) return;
    await consumeStream(
      api.regenerateStream(conversationId, message.id, provider, model.trim(), temperature),
    );
  }

  function beginEdit(message: Message) {
    if (sending || loading || uncertain || draft.trim()) return;
    setEditTarget(message);
    setDraft(message.content);
    setError('');
    queueMicrotask(() => inputRef.current?.focus());
  }

  function cancelEdit() {
    setEditTarget(null);
    setDraft('');
    setError('');
    inputRef.current?.focus();
  }

  async function stopGeneration() {
    if (!sending || !generationId || phase === 'stopping') return;
    setPhase('stopping');
    try {
      await api.stopGeneration(generationConversationId ?? conversationId, generationId);
    } catch (e) {
      setError(errorMessage(e));
      setPhase('generating');
    }
  }

  const phaseText = phase === 'generating' ? '応答を生成中'
    : phase === 'secondary_recall' ? '関連する記憶を追加確認中'
      : phase === 'repairing' ? '品質チェックに基づいて応答を修正中'
        : phase === 'stopping' ? '生成を停止中'
          : '応答を検証中';

  const first = messages[0];
  const last = messages[messages.length - 1];
  const page = (params: WindowRequest) => { setFocusMessage(null); void load(params).catch(e => setError(errorMessage(e))); };
  return <section className="chat-panel" aria-label={`${name}との会話`}>
    <div className="chat-toolbar">
      <div><span className="avatar" aria-hidden="true">{name.slice(0, 1)}</span><strong>{name}</strong><span className="pill">保存された会話</span></div>
      <button onClick={() => setSummaryOpen(!summaryOpen)} aria-expanded={summaryOpen} disabled={sending}>会話の要約</button>
    </div>
    <div className={`chat-content ${summaryOpen ? 'with-summary' : ''}`}>
      <div className="transcript-column">
        <nav className="history-pager" aria-label="履歴ページ">
          <button disabled={sending || loading || !hasOlder || !first} onClick={() => first && page({ before: first.position })}>前の100件</button>
          <span>{loading ? '履歴を読込中…' : `${messages.length}件を表示${latest ? ' · 最新' : ''}`}</span>
          <button disabled={sending || loading || latest || !last} onClick={() => last && page({ after: last.position })}>次の100件</button>
          <button disabled={sending || loading} onClick={() => page({ tail: true })}>履歴を再読込</button>
        </nav>
        <div className="transcript" role="log" aria-label="会話履歴" aria-live="polite" aria-busy={loading}>
          {!loading && !messages.length && <div className="conversation-empty"><span className="large-initial" aria-hidden="true">{name.slice(0, 1)}</span><h2>{name}と話してみましょう</h2><p>キャラクター設定と記憶を参照しながら、<br />この会話を少しずつ続けていきます。</p></div>}
          {messages.map(message => <article key={message.id} id={`message-${message.id}`} data-testid="message" className={`message ${message.role} ${focusMessage === message.id ? 'highlighted' : ''}`}>
            <header><strong>{message.role === 'user' ? 'あなた' : message.role === 'assistant' ? name : 'システム'}</strong>
              {message.model && <small>{message.provider} / {message.model}</small>}</header>
            {message.role === 'assistant'
              ? <div className="markdown"><Markdown skipHtml components={{
                  img: ({ alt }) => <span className="muted">［画像: {alt || '外部画像は読み込みません'}］</span>,
                  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
                }}>{message.content}</Markdown></div>
              : <p className="plain-message">{message.content}</p>}
            <div className="message-actions">
              {message.role === 'assistant' && <button type="button" disabled={sending || loading || uncertain || Boolean(draft.trim()) || Boolean(editTarget)} onClick={() => void regenerate(message)}>再生成</button>}
              {message.role === 'user' && <button type="button" disabled={sending || loading || uncertain || Boolean(draft.trim())} onClick={() => beginEdit(message)}>編集して再送</button>}
            </div>
          </article>)}
          {sending && preview && <article data-testid="draft-preview" className="message assistant draft-preview">
            <header><strong>{name}</strong><small>未確定の下書き · Finalで置換されます</small></header>
            <div className="markdown"><Markdown skipHtml components={{
              img: ({ alt }) => <span className="muted">［画像: {alt || '外部画像は読み込みません'}］</span>,
              a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
            }}>{preview}</Markdown></div>
          </article>}
          <div ref={endRef} />
        </div>
      </div>
      {summaryOpen && <aside className="summary-panel" aria-label="会話要約">
        <h3>会話の要約</h3><p className="muted">出典付きの抜粋です。全文の意味をすべて保持するものではありません。</p>
        {summaryLoading && <p role="status">要約を読込中…</p>}
        {summaryError && <p role="alert" className="error">{summaryError}</p>}
        {summary && <><small>{summary.covered_messages}件を処理済み · {summary.entries.length}件の抜粋</small>
          {!summary.entries.length && <p>会話が長くなると、ここに要約が蓄積されます。</p>}
          {summary.entries.map(entry => <section key={entry.source_message_id} className="summary-entry"><p>{entry.excerpt}</p>
            <button disabled={sending || loading} onClick={() => {
              setFocusMessage(entry.source_message_id);
              void load({ after: entry.position - 1 }).catch(e => setError(errorMessage(e)));
            }}>出典を見る（{entry.role === 'user' ? 'あなた' : name}）</button></section>)}
        </>}
      </aside>}
    </div>
    <div className="composer-area">
      {error && <p role="alert" className="error">{error}</p>}
      {sending && <p className="generation-status" role="status">{phaseText}。表示中の下書きは未確定で、保存されません。</p>}
      {result && !sending && <p className="success" role="status">品質チェック済み · {result.quality_mode === 'fast' ? 'Fast' : result.quality_mode === 'strict' ? 'Strict' : 'Balanced'}{result.repaired ? ' · 応答を修正しました' : ''}{result.regenerated_for_recall ? ' · 記憶を追加して再生成しました' : ''}</p>}
      {editTarget && !sending && <div className="edit-retry-banner" role="status"><span>この発言から新しい会話へ分岐します。元の履歴は残ります。</span><button type="button" onClick={cancelEdit}>編集をやめる</button></div>}
      <form ref={formRef} onSubmit={submit} className="composer">
        <label className="sr-only" htmlFor="chat-input">メッセージ</label>
        <textarea ref={inputRef} id="chat-input" rows={3} maxLength={4000} value={draft} disabled={sending} placeholder={`${name}へのメッセージ…`} onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing && e.keyCode !== 229) {
              e.preventDefault(); formRef.current?.requestSubmit();
            }
          }} />
        {sending
          ? <button type="button" className="danger" disabled={!generationId || phase === 'stopping'} onClick={() => void stopGeneration()}>{phase === 'stopping' ? '停止中…' : '停止'}</button>
          : <button className="primary" disabled={loading || uncertain || !draft.trim() || !model.trim() || !provider}>{editTarget ? '編集して分岐' : '送信'}</button>}
      </form>
      <div className="composer-hint"><span>{editTarget ? '編集内容は新しいbranchにだけ保存されます' : 'Ctrl / ⌘ + Enterで送信 · 下書きはこのタブ内のみ'}</span><span>{draft.length} / 4,000</span></div>
    </div>
  </section>;
}
