import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { errorMessage } from './api';
import { listFields } from './types';
import type { Character, CharacterInput, ListField } from './types';

const labels: Record<ListField, string> = {
  speech_style: '口調', personality: '性格', values: '価値観', likes: '好きなもの',
  dislikes: '苦手なもの', background: '生い立ち', lore: '世界設定', forbidden: '禁止フレーズ',
  relationship: 'あなたとの関係', response_style: '応答スタイル',
};
export function parseCharacter(value: unknown): CharacterInput {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('JSONオブジェクトを指定してください。');
  const record = value as Record<string, unknown>;
  const allowed = new Set<string>(['id', 'name', 'first_person', 'second_person', ...listFields]);
  if (Object.keys(record).some(key => !allowed.has(key))) throw new Error('この形式には未対応の設定項目が含まれています。');
  if (typeof record.name !== 'string' || !record.name.trim() || record.name.length > 200) throw new Error('名前は1〜200文字で指定してください。');
  for (const key of ['first_person', 'second_person']) {
    if (record[key] != null && typeof record[key] !== 'string') throw new Error('一人称・二人称には文字列を指定してください。');
  }
  for (const key of listFields) {
    if (record[key] !== undefined && (!Array.isArray(record[key]) || !(record[key] as unknown[]).every(x => typeof x === 'string'))) {
      throw new Error(`${labels[key]}には文字列の配列を指定してください。`);
    }
  }
  const result = {
    name: record.name.trim(),
    first_person: (record.first_person as string | undefined) || null,
    second_person: (record.second_person as string | undefined) || null,
    ...Object.fromEntries(listFields.map(key => [key, ((record[key] as string[] | undefined) ?? []).map(item => item.trim()).filter(Boolean)])),
  } as CharacterInput;
  // Leave room for the ID emitted by the backend.
  if (new TextEncoder().encode(JSON.stringify(result)).length > 11_900) throw new Error('設定が大きすぎます。約12KB以内に収めてください。');
  return result;
}
const empty: CharacterInput = {
  name: '', first_person: null, second_person: null,
  speech_style: [], personality: [], values: [], likes: [], dislikes: [],
  background: [], lore: [], forbidden: [], relationship: [], response_style: [],
};

export function CharacterEditor({ initial, onSave, onClose }: {
  initial?: Character;
  onSave: (data: CharacterInput, id?: string) => Promise<void>;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [data, setData] = useState<CharacterInput>(initial ?? empty);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const busy = saving || importing;
  useEffect(() => { dialog.current?.showModal(); }, []);

  async function importFile(file?: File) {
    if (!file) return;
    setError(''); setImporting(true);
    try {
      if (file.size > 12_000) throw new Error('JSONファイルは12KB以内にしてください。');
      setData(parseCharacter(JSON.parse(await file.text())));
    } catch (e) { setError(errorMessage(e)); }
    finally { setImporting(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError(''); setSaving(true);
    try { await onSave(parseCharacter(data), initial?.id); onClose(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setSaving(false); }
  }
  return <dialog ref={dialog} aria-labelledby="editor-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={submit}>
      <header className="dialog-heading"><div><p className="eyebrow">CHARACTER CORE</p><h2 id="editor-title">{initial ? 'キャラクターを編集' : 'キャラクターを追加'}</h2></div>
        <button type="button" className="quiet" onClick={onClose} disabled={busy} aria-label="編集画面を閉じる">閉じる</button></header>
      <p className="muted">固定設定として毎回参照します。各設定は1行に1項目ずつ入力してください。</p>
      <fieldset disabled={busy}>
        <label>定義JSONを読み込む<input type="file" accept=".json,application/json" onChange={e => { void importFile(e.target.files?.[0]); e.target.value = ''; }} /></label>
        <small>独自のCharacter Core形式に対応。新規登録では新しいIDを発行します。</small>
        <label>名前<input autoFocus required maxLength={200} value={data.name} onChange={e => setData({ ...data, name: e.target.value })} /></label>
        <div className="two-column">
          <label>一人称<input value={data.first_person ?? ''} onChange={e => setData({ ...data, first_person: e.target.value })} placeholder="私" /></label>
          <label>二人称<input value={data.second_person ?? ''} onChange={e => setData({ ...data, second_person: e.target.value })} placeholder="あなた" /></label>
        </div>
        {listFields.map(key => <label key={key}>{labels[key]}<textarea rows={2} value={data[key].join('\n')} onChange={e => setData({ ...data, [key]: e.target.value.split('\n') })} /></label>)}
        <small>禁止フレーズは現在、文字列一致による検出です。意味的な禁止事項の完全な判定ではありません。</small>
      </fieldset>
      {error && <p role="alert" className="error">{error}</p>}
      <footer className="dialog-footer"><button type="button" onClick={onClose} disabled={busy}>キャンセル</button><button className="primary" disabled={busy || !data.name.trim()}>{saving ? '保存中…' : '設定を保存'}</button></footer>
    </form>
  </dialog>;
}
