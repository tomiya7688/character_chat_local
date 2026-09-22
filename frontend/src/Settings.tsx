import { useEffect, useRef, useState } from 'react';

export function Settings({ token, base, onApply, onClose }: {
  token: string; base: string; onApply: (token: string) => void; onClose: () => void;
}) {
  const [value, setValue] = useState(token);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} aria-labelledby="settings-title" onCancel={e => { e.preventDefault(); onClose(); }}>
    <form onSubmit={e => { e.preventDefault(); onApply(value.trim()); }}>
      <header className="dialog-heading"><div><p className="eyebrow">LOCAL CONNECTION</p><h2 id="settings-title">接続設定</h2></div><button className="quiet" type="button" onClick={onClose}>閉じる</button></header>
      <p>接続先: <code>{base || window.location.origin}</code></p>
      <label>ローカルAPIトークン<input type="password" autoComplete="off" value={value} onChange={e => setValue(e.target.value)} /></label>
      <p className="muted"><code>CHARACTER_CHAT_API_TOKEN</code>を設定した場合のみ必要です。トークンはメモリ内だけに保持し、画面の再読込で消えます。</p>
      <h3>モデルへの接続</h3>
      <p>Ollamaはバックエンドから接続します。クラウドProviderのAPIキーは、この画面では入力・保存しません。</p>
      <p className="muted">バックエンドで <code>OLLAMA_BASE_URL</code>、<code>OPENAI_API_KEY</code>、<code>GEMINI_API_KEY</code>、<code>XAI_API_KEY</code> を設定して再起動してください。</p>
      <p className="muted">開発時の接続先は <code>VITE_API_BASE_URL</code>。本番ビルドはAPIと同じlocalhostから配信します。LANへの公開は対象外です。</p>
      <footer className="dialog-footer"><button type="button" onClick={() => setValue('')}>トークンを消去</button><button className="primary">適用して再接続</button></footer>
    </form>
  </dialog>;
}
