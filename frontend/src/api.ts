import type { Character, CharacterInput, ChatResult, ChatStreamEvent, Conversation, Message, Model, Summary } from './types';

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

function apiBase(): string {
  const value = (import.meta.env.VITE_API_BASE_URL ?? '').trim();
  if (!value) return '';
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol)
    || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('API接続先は認証情報を含まないlocalhostのルートURLにしてください。');
  }
  return url.origin;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '処理に失敗しました。';
}

export class ApiClient {
  readonly base = apiBase();
  constructor(private readonly token = '') {}

  private responseError(status: number, data: unknown): ApiError {
    const detail = (data as { detail?: { code?: string } } | null)?.detail;
    const code = typeof detail === 'object' && detail !== null ? detail.code : undefined;
    const message = code === 'quality_rejected'
      ? '品質チェックを通過する応答が得られませんでした。入力は未保存です。内容やモデルを変えて再送できます。'
      : ({ 401: 'ローカルAPIトークンを接続設定に入力してください。',
        403: '接続元が許可されていません。バックエンドのOrigin設定を確認してください。',
        404: '対象が見つかりません。一覧を再読込してください。',
        409: '別の生成または更新と競合しました。履歴を再読込してから再送してください。',
        422: '入力または設定が上限を超えています。文字数やキャラクター設定を確認してください。',
        502: 'モデルへの接続に失敗しました。Ollamaの起動・モデル・Provider設定を確認してください。',
      } as Record<number, string>)[status]
        ?? `処理に失敗しました（HTTP ${status}）。`;
    return new ApiError(message, status, code);
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body) headers.set('Content-Type', 'application/json');
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`);
    let response: Response;
    try {
      response = await fetch(`${this.base}${path}`, {
        ...init, headers, credentials: 'omit', cache: 'no-store', redirect: 'error',
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ApiError('接続が切れました。会話を再読込して保存状況を確認してから再送してください。', 0);
    }
    let data: unknown;
    try { data = await response.json(); }
    catch { throw new ApiError('APIから正しい応答を取得できませんでした。接続先を確認してください。', response.status); }
    if (!response.ok) {
      // Never display an arbitrary provider error/body: it may contain credentials or drafts.
      throw this.responseError(response.status, data);
    }
    return data as T;
  }

  characters(signal?: AbortSignal) { return this.request<Character[]>('/characters?limit=500', { signal }); }
  conversations(signal?: AbortSignal) { return this.request<Conversation[]>('/conversations?limit=500', { signal }); }
  providers(signal?: AbortSignal) { return this.request<{ providers: string[] }>('/providers', { signal }); }
  models(id: string, signal?: AbortSignal) {
    return this.request<Model[]>(`/providers/${encodeURIComponent(id)}/models`, { signal });
  }
  saveCharacter(data: CharacterInput, id?: string) {
    return this.request<Character>(id ? `/characters/${encodeURIComponent(id)}` : '/characters', {
      method: id ? 'PUT' : 'POST', body: JSON.stringify(id ? { ...data, id } : data),
    });
  }
  createConversation(characterId: string) {
    return this.request<Conversation>('/conversations', {
      method: 'POST', body: JSON.stringify({ character_id: characterId }),
    });
  }
  messages(id: string, params: { tail?: boolean; before?: number; after?: number } = { tail: true }, signal?: AbortSignal) {
    const query = new URLSearchParams({ limit: '100' });
    for (const [key, value] of Object.entries(params)) query.set(key, String(value));
    return this.request<Message[]>(`/conversations/${encodeURIComponent(id)}/messages?${query}`, { signal });
  }
  summary(id: string, signal?: AbortSignal) {
    return this.request<Summary>(`/conversations/${encodeURIComponent(id)}/summary`, { signal });
  }
  private async *streamRequest(path: string, body: object): AsyncGenerator<ChatStreamEvent> {
    const headers = new Headers({ 'Content-Type': 'application/json' });
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`);
    let response: Response;
    try {
      response = await fetch(`${this.base}${path}`, {
        method: 'POST',
        headers,
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
        body: JSON.stringify(body),
      });
    } catch {
      throw new ApiError('接続が切れました。履歴を再読込して保存状況を確認してから再送してください。', 0);
    }
    if (!response.ok) {
      let data: unknown = null;
      try { data = await response.json(); } catch { /* generic status message below */ }
      throw this.responseError(response.status, data);
    }
    if (!response.body) throw new ApiError('ストリーム応答を読み取れませんでした。', 0);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let newline = buffer.indexOf('\n');
        while (newline >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (line) yield this.streamEvent(line);
          newline = buffer.indexOf('\n');
        }
        if (done) break;
      }
      if (buffer.trim()) yield this.streamEvent(buffer.trim());
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError('生成ストリームが切れました。履歴を再読込して保存状況を確認してください。', 0);
    } finally {
      reader.releaseLock();
    }
  }

  chatStream(
    id: string,
    provider: string,
    model: string,
    userInput: string,
    temperature: number,
  ) {
    return this.streamRequest(
      `/conversations/${encodeURIComponent(id)}/chat/stream`,
      { provider, model, user_input: userInput, temperature },
    );
  }

  regenerateStream(
    id: string,
    messageId: string,
    provider: string,
    model: string,
    temperature: number,
  ) {
    return this.streamRequest(
      `/conversations/${encodeURIComponent(id)}/messages/${encodeURIComponent(messageId)}/regenerate/stream`,
      { provider, model, temperature },
    );
  }

  editRetryStream(
    id: string,
    messageId: string,
    provider: string,
    model: string,
    userInput: string,
    temperature: number,
  ) {
    return this.streamRequest(
      `/conversations/${encodeURIComponent(id)}/messages/${encodeURIComponent(messageId)}/edit-retry/stream`,
      { provider, model, user_input: userInput, temperature },
    );
  }

  private streamEvent(line: string): ChatStreamEvent {
    let value: unknown;
    try { value = JSON.parse(line); }
    catch { throw new ApiError('生成ストリームの形式が壊れています。履歴を再読込してください。', 0); }
    if (!value || typeof value !== 'object' || typeof (value as { type?: unknown }).type !== 'string') {
      throw new ApiError('生成ストリームのイベントを確認できませんでした。', 0);
    }
    return value as ChatStreamEvent;
  }

  stopGeneration(id: string, generationId: string) {
    return this.request<{ generation_id: string; status: string }>(
      `/conversations/${encodeURIComponent(id)}/generations/${encodeURIComponent(generationId)}/stop`,
      { method: 'POST' },
    );
  }

  chat(id: string, provider: string, model: string, userInput: string, temperature: number) {
    // No transport retry: a lost response may already have been committed by the server.
    return this.request<ChatResult>(`/conversations/${encodeURIComponent(id)}/chat`, {
      method: 'POST', body: JSON.stringify({ provider, model, user_input: userInput, temperature }),
    });
  }
}
