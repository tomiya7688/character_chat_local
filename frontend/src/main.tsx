import { Component, StrictMode } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed
      ? <main className="startup-error"><h1>画面を表示できませんでした</h1><p>接続先の設定を確認して、画面を再読込してください。確定した会話はローカルDBに残っています。</p><button onClick={() => window.location.reload()}>再読込</button></main>
      : this.props.children;
  }
}

const root = document.getElementById('root');
if (root) createRoot(root).render(<StrictMode><Boundary><App /></Boundary></StrictMode>);
