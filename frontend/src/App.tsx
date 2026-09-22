import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiClient, errorMessage } from './api';
import { CharacterEditor } from './CharacterEditor';
import { ChatPanel } from './ChatPanel';
import { Settings } from './Settings';
import type { Character, CharacterInput, Conversation, Model } from './types';

function updateLocation(id: string) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set('conversation', id);
  else url.searchParams.delete('conversation');
  window.history.replaceState(null, '', url);
}

export default function App() {
  const [token, setToken] = useState('');
  const api = useMemo(() => new ApiClient(token), [token]);
  const [refresh, setRefresh] = useState(0);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [models, setModels] = useState<Model[]>([]);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState('');
  const [manual, setManual] = useState(false);
  const manualRef = useRef(false);
  const [modelRefresh, setModelRefresh] = useState(0);
  const [characterId, setCharacterId] = useState('');
  const [conversationId, setConversationId] = useState(() => new URL(window.location.href).searchParams.get('conversation') ?? '');
  const selectedRef = useRef(conversationId);
  selectedRef.current = conversationId;
  const [temperature, setTemperature] = useState(0.8);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [settings, setSettings] = useState(false);
  const [editor, setEditor] = useState<Character | 'new' | null>(null);
  const [mobileMenu, setMobileMenu] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setConnected(false); setError('');
    void Promise.all([api.characters(controller.signal), api.conversations(controller.signal), api.providers(controller.signal)])
      .then(([chars, chats, configured]) => {
        if (controller.signal.aborted) return;
        setCharacters(chars); setConversations(chats); setProviders(configured.providers);
        setProvider(current => configured.providers.includes(current) ? current : configured.providers.includes('ollama') ? 'ollama' : configured.providers[0] ?? '');
        const saved = chats.find(chat => chat.id === selectedRef.current);
        setConversationId(saved?.id ?? '');
        updateLocation(saved?.id ?? '');
        setCharacterId(current => saved?.character_id ?? (chars.some(char => char.id === current) ? current : chars[0]?.id ?? ''));
        setConnected(true);
      }).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, refresh]);

  useEffect(() => {
    if (!provider || !connected) return;
    const controller = new AbortController();
    setModelLoading(true); setModelError(''); setModels([]);
    if (!manualRef.current) setModel('');
    void api.models(provider, controller.signal).then(items => {
      if (controller.signal.aborted) return;
      setModels(items);
      if (!manualRef.current) setModel(current => items.some(item => item.id === current) ? current : items[0]?.id ?? '');
      if (!items.length) setModelError('モデルがありません。Ollamaにモデルを用意するか、モデルIDを直接指定してください。');
    }).catch(e => { if (!controller.signal.aborted) setModelError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setModelLoading(false); });
    return () => controller.abort();
  }, [api, provider, connected, modelRefresh]);

  const character = characters.find(item => item.id === characterId);
  const locked = busy || loading;
  const selectConversation = (chat: Conversation) => {
    setConversationId(chat.id); setCharacterId(chat.character_id); updateLocation(chat.id); setMobileMenu(false); setError('');
  };
  async function startConversation() {
    if (locked || !characterId) return;
    setBusy(true); setError('');
    try {
      const chat = await api.createConversation(characterId);
      setConversations(current => [chat, ...current].slice(0, 500)); selectConversation(chat);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function saveCharacter(data: CharacterInput, id?: string) {
    const saved = await api.saveCharacter(data, id);
    setCharacters(current => id ? current.map(item => item.id === id ? saved : item) : [...current, saved]);
    if (!id) { setCharacterId(saved.id); setConversationId(''); updateLocation(''); }
  }

  return <div className="app-shell">
    <header className="app-heading">
      <button className="mobile-toggle" onClick={() => setMobileMenu(!mobileMenu)} aria-expanded={mobileMenu} aria-controls="workspace-navigation">メニュー</button>
      <div className="brand"><span className="brand-mark" aria-hidden="true">C</span><div><h1>Character Chat <span>Local</span></h1><p>会話を、少しずつ重ねて。</p></div></div>
      <div className="heading-actions"><span className="connection-state">{loading ? '接続中' : connected ? 'ローカル接続' : '未接続'}</span><button onClick={() => setSettings(true)} disabled={locked}>接続設定</button></div>
    </header>
    <div className="workspace">
      <aside id="workspace-navigation" className={`sidebar ${mobileMenu ? 'is-open' : ''}`}>
        <div className="section-heading"><h2>キャラクター</h2><button className="quiet" onClick={() => setEditor('new')} disabled={locked || !connected}>追加</button></div>
        <label className="sr-only" htmlFor="character-select">キャラクターを選択</label>
        <select id="character-select" value={characterId} disabled={locked || !connected} onChange={e => { setCharacterId(e.target.value); setConversationId(''); updateLocation(''); }}>
          {!characters.length && <option value="">キャラクター未登録</option>}
          {characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        {character && <div className="character-card"><span className="large-initial" aria-hidden="true">{character.name.slice(0, 1)}</span><h3>{character.name}</h3><p>{character.personality.filter(Boolean).slice(0, 2).join(' · ') || 'まだ知らない一面を、会話の中で。'}</p><button onClick={() => setEditor(character)} disabled={locked}>設定を編集</button></div>}
        <button className="primary start-chat" disabled={locked || !character} onClick={() => void startConversation()}>新しい会話</button>
        <div className="section-heading conversations-heading"><h2>これまでの会話</h2><button className="quiet" disabled={locked} onClick={() => setRefresh(value => value + 1)}>一覧更新</button></div>
        <nav className="conversation-list" aria-label="保存した会話">
          {conversations.filter(chat => chat.character_id === characterId).map((chat, index) => <button key={chat.id} className={chat.id === conversationId ? 'selected' : ''} aria-current={chat.id === conversationId ? 'page' : undefined} disabled={locked} onClick={() => selectConversation(chat)}>
            <span>会話 {chat.id.slice(0, 8)}</span><small>{index === 0 ? '最近の会話' : '保存済み'}</small></button>)}
          {!conversations.some(chat => chat.character_id === characterId) && <p className="muted">会話はまだありません。</p>}
        </nav>
        <footer className="sidebar-footer">会話はローカルDBに保存します。<br />一覧は最大500件まで表示します。</footer>
      </aside>
      <main>
        <section className="model-bar" aria-label="生成設定">
          <label>Provider<select value={provider} disabled={locked || !connected} onChange={e => { manualRef.current = false; setManual(false); setModel(''); setProvider(e.target.value); }}>
            {!providers.length && <option value="">未設定</option>}{providers.map(id => <option key={id} value={id}>{id}</option>)}</select></label>
          <label className="model-field">モデル{manual
            ? <input aria-label="モデルID" value={model} maxLength={200} disabled={locked || !connected} onChange={e => setModel(e.target.value)} placeholder="インストール済みのモデルID" />
            : <select aria-label="モデル" value={model} disabled={locked || modelLoading || !connected} onChange={e => setModel(e.target.value)}>
              {!models.length && <option value="">{modelLoading ? 'モデルを読込中…' : 'モデルを選択'}</option>}{models.map(item => <option key={item.id} value={item.id}>{item.display_name || item.id}</option>)}</select>}</label>
          <label className="temperature-field">Temperature<input type="number" min={0} max={2} step={0.1} value={temperature} disabled={locked} onChange={e => { const value = e.target.valueAsNumber; if (Number.isFinite(value)) setTemperature(Math.min(2, Math.max(0, value))); }} /></label>
          <label className="checkbox"><input type="checkbox" checked={manual} disabled={locked} onChange={e => { manualRef.current = e.target.checked; setManual(e.target.checked); setModel(e.target.checked ? model : models[0]?.id ?? ''); }} />IDを直接指定</label>
          <button disabled={locked || modelLoading || !connected} onClick={() => setModelRefresh(value => value + 1)}>モデル更新</button>
        </section>
        {modelError && connected && <p className="model-warning" role="status">{modelError}</p>}
        {error && <p className="error workspace-error" role="alert">{error}</p>}
        {connected && conversationId && character
          ? <ChatPanel key={`${conversationId}:${refresh}`} api={api} conversationId={conversationId} name={character.name} provider={provider} model={model} temperature={temperature} onBusy={setBusy} />
          : <section className="welcome"><p className="eyebrow">YOUR LOCAL CONVERSATION SPACE</p><h2>{loading ? '会話の準備をしています' : 'ここから、会話をはじめよう。'}</h2><p>キャラクターとモデルを選んで、あなたのペースで。<br />設定も、これまでの会話も、この場所に残ります。</p>
            {!loading && connected && !characters.length && <button className="primary" onClick={() => setEditor('new')}>最初のキャラクターを追加</button>}
            {!loading && connected && character && <button className="primary" disabled={busy} onClick={() => void startConversation()}>会話をはじめる</button>}
            {!loading && !connected && <button className="primary" onClick={() => setSettings(true)}>接続設定を開く</button>}
            <div className="welcome-note"><strong>検証してから、届ける。</strong><p>モデルの出力は品質チェック後に表示します。<br />検証中の下書きは、会話には追加されません。</p></div>
          </section>}
      </main>
    </div>
    {editor && <CharacterEditor initial={editor === 'new' ? undefined : editor} onSave={saveCharacter} onClose={() => setEditor(null)} />}
    {settings && <Settings token={token} base={api.base} onApply={value => { setToken(value); setRefresh(current => current + 1); setSettings(false); }} onClose={() => setSettings(false)} />}
  </div>;
}
