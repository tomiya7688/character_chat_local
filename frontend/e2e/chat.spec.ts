import { expect, test } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';

const headers = { Authorization: 'Bearer webui-test-token' };

async function connect(page: Page) {
  await page.getByRole('button', { name: '接続設定を開く', exact: true }).click();
  await page.getByLabel('ローカルAPIトークン', { exact: true }).fill('webui-test-token');
  await page.getByRole('button', { name: '適用して再接続' }).click();
  await expect(page.getByLabel('モデル', { exact: true })).toHaveValue('test-small');
}

async function newChat(page: Page, request: APIRequestContext, name: string) {
  const response = await request.post('/characters', { headers, data: { name } });
  expect(response.status()).toBe(201);
  const character = await response.json() as { id: string };
  const created = await request.post('/conversations', { headers, data: { character_id: character.id } });
  const conversation = await created.json() as { id: string };
  await page.goto(`/ui/?conversation=${conversation.id}`);
  await connect(page);
  await expect(page.getByLabel('メッセージ', { exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: '履歴を再読込' })).toBeEnabled();
  return conversation.id;
}

async function send(page: Page, text: string) {
  await page.getByLabel('メッセージ', { exact: true }).fill(text);
  await page.getByRole('button', { name: '送信', exact: true }).click();
}

async function stored(request: APIRequestContext, id: string) {
  return (await request.get(`/conversations/${id}/messages`, { headers })).json() as Promise<unknown[]>;
}

test('JSON import, character editing, conversation, model switch and reload', async ({ page, request }, testInfo) => {
  await page.goto('/ui/'); await connect(page);
  await page.getByRole('button', { name: '追加', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('定義JSONを読み込む').setInputFiles({
    name: 'mika.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ name: 'ミカ', first_person: '私', lore: ['海辺の町に住む'], personality: ['穏やか', '好奇心旺盛'], forbidden: [''] })),
  });
  await expect(dialog.getByLabel('名前', { exact: true })).toHaveValue('ミカ');
  await dialog.getByLabel('あなたとの関係', { exact: true }).fill('幼なじみ');
  await dialog.getByRole('button', { name: '設定を保存' }).click();
  await expect(dialog).not.toBeVisible();
  const characters = await (await request.get('/characters?limit=500', { headers })).json() as { name: string; lore: string[]; relationship: string[]; forbidden: string[] }[];
  const mika = characters.find(item => item.name === 'ミカ');
  expect(mika?.lore).toEqual(['海辺の町に住む']);
  expect(mika?.relationship).toEqual(['幼なじみ']);
  expect(mika?.forbidden).toEqual([]);
  await page.getByRole('button', { name: '新しい会話', exact: true }).click();
  await expect(page.getByRole('button', { name: '履歴を再読込' })).toBeEnabled();
  await send(page, '今日は海がきれいだね');
  await expect(page.getByTestId('message')).toHaveCount(2);
  await expect(page.locator('.message.assistant')).toContainText('[test-small] 今日は海がきれいだね を受け取ったよ。');
  await page.getByLabel('モデル', { exact: true }).selectOption('test-alt');
  await send(page, '次は灯台へ行こう');
  await expect(page.getByTestId('message')).toHaveCount(4);
  await expect(page.locator('.message.assistant').last()).toContainText('ollama / test-alt');
  await page.screenshot({ path: testInfo.outputPath('desktop-chat.png'), fullPage: true });
  await page.reload(); await connect(page);
  await expect(page.getByTestId('message')).toHaveCount(4);
  await page.getByRole('button', { name: '設定を編集' }).click();
  await expect(page.getByRole('dialog').getByLabel('世界設定', { exact: true })).toHaveValue('海辺の町に住む');
  await page.getByRole('dialog').getByLabel('口調', { exact: true }).fill('やさしい話し方');
  await page.getByRole('dialog').getByRole('button', { name: '設定を保存' }).click();
  await expect(page.getByTestId('message')).toHaveCount(4);
});

test('rejected drafts never display or enter history; input can be corrected', async ({ page, request }) => {
  const id = await newChat(page, request, '品質確認');
  await send(page, '拒否テスト');
  await expect(page.getByRole('alert')).toContainText('品質チェックを通過する応答が得られませんでした');
  await expect(page.getByLabel('メッセージ', { exact: true })).toHaveValue('拒否テスト');
  await expect(page.getByTestId('message')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('As an AI');
  expect(await stored(request, id)).toHaveLength(0);
  await send(page, 'もう一度こんにちは');
  await expect(page.getByTestId('message')).toHaveCount(2);
});

test('repair status reflects the actual validated API result', async ({ page, request }) => {
  await newChat(page, request, '修正確認');
  await page.getByLabel('モデル', { exact: true }).selectOption('repair-model');
  await send(page, '修正の動作を確認する');
  await expect(page.getByTestId('message')).toHaveCount(2);
  await expect(page.locator('.success')).toContainText('応答を修正しました');
  await expect(page.locator('body')).not.toContainText('As an AI');
});

test('provider failure preserves input and requires reconciliation before retry', async ({ page, request }) => {
  const id = await newChat(page, request, '接続確認');
  await page.getByLabel('モデル', { exact: true }).selectOption('offline');
  await send(page, '消さないでほしい入力');
  await expect(page.getByRole('alert')).toContainText('モデルへの接続に失敗しました');
  await expect(page.getByLabel('メッセージ', { exact: true })).toHaveValue('消さないでほしい入力');
  await expect(page.locator('body')).not.toContainText('DO_NOT_LEAK');
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeDisabled();
  expect(await stored(request, id)).toHaveLength(0);
  await page.getByLabel('モデル', { exact: true }).selectOption('test-small');
  await page.getByRole('button', { name: '履歴を再読込' }).click();
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '送信', exact: true }).click();
  await expect(page.getByTestId('message')).toHaveCount(2);
});

test('2000 messages remain paginated, including gaps in global message positions', async ({ page, request }) => {
  const fixture = await (await request.get('/e2e/history', { headers })).json() as { conversation_id: string };
  const messageRequests: string[] = [];
  page.on('request', request => { if (request.url().includes('/messages?')) messageRequests.push(request.url()); });
  await page.goto(`/ui/?conversation=${fixture.conversation_id}`); await connect(page);
  await expect(page.getByTestId('message')).toHaveCount(100);
  await expect(page.getByTestId('message').last()).toContainText('履歴 1999');
  expect(messageRequests).toHaveLength(1);
  expect(messageRequests[0]).toContain('tail=true');
  await page.getByRole('button', { name: '前の100件' }).click();
  await expect(page.getByTestId('message').first()).toContainText('履歴 1800');
  await expect(page.getByTestId('message')).toHaveCount(100);
  await page.getByRole('button', { name: '次の100件' }).click();
  await expect(page.getByTestId('message').last()).toContainText('履歴 1999');
  expect(messageRequests.every(url => url.includes('limit=100'))).toBe(true);
});

test('Markdown/code render without raw HTML, script URLs or external image requests', async ({ page, request }) => {
  const external: string[] = [];
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:8766/')) external.push(request.url()); });
  await newChat(page, request, '安全な表示');
  await send(page, '表示テスト');
  await expect(page.getByTestId('message')).toHaveCount(2);
  await expect(page.locator('.markdown h2')).toHaveText('見出し');
  await expect(page.locator('.markdown strong')).toHaveText('強調された文章');
  await expect(page.locator('.markdown pre code')).toContainText("print('hello')");
  await expect(page.locator('.markdown img')).toHaveCount(0);
  expect(await page.evaluate(() => (window as Window & { __xss?: boolean }).__xss)).toBeUndefined();
  expect(await page.locator('.markdown a').evaluateAll(links => links.every(link => !(link.getAttribute('href') ?? '').toLowerCase().startsWith('javascript:')))).toBe(true);
  expect(external).toEqual([]);
});

test('IME confirmation and repeated submit do not send extra turns', async ({ page, request }) => {
  const id = await newChat(page, request, '入力確認');
  const input = page.getByLabel('メッセージ', { exact: true });
  await input.fill('変換中');
  await input.dispatchEvent('keydown', { key: 'Enter', ctrlKey: true, isComposing: true, keyCode: 229 });
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeEnabled();
  expect(await stored(request, id)).toHaveLength(0);
  await input.press('End'); await input.press('Enter');
  await expect(input).toHaveValue('変換中\n');
  await input.fill('一回だけ送る');
  await page.locator('form.composer').evaluate(form => { (form as HTMLFormElement).requestSubmit(); (form as HTMLFormElement).requestSubmit(); });
  await expect(page.getByTestId('message')).toHaveCount(2);
  expect(await stored(request, id)).toHaveLength(2);
});

test('invalid JSON imports leave the editor usable', async ({ page }) => {
  await page.goto('/ui/'); await connect(page);
  await page.getByRole('button', { name: '追加', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('名前', { exact: true }).fill('編集中');
  await dialog.getByLabel('定義JSONを読み込む').setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{"name":"bad","personality":42}') });
  await expect(dialog.getByRole('alert')).toContainText('性格には文字列の配列');
  await expect(dialog.getByLabel('名前', { exact: true })).toHaveValue('編集中');
  await dialog.getByLabel('定義JSONを読み込む').setInputFiles({ name: 'big.json', mimeType: 'application/json', buffer: Buffer.alloc(12_001, ' ') });
  await expect(dialog.getByRole('alert')).toContainText('12KB以内');
  await dialog.getByRole('button', { name: 'キャンセル' }).click();
  await expect(dialog).not.toBeVisible();
});

test('API token stays out of storage and URLs and must be reentered after reload', async ({ page, request }) => {
  await newChat(page, request, '認証確認');
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })) ).toEqual({ local: 0, session: 0 });
  expect(page.url()).not.toContain('webui-test-token');
  await expect(page.locator('body')).not.toContainText('webui-test-token');
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('ローカルAPIトークン');
  await expect(page.getByRole('button', { name: '接続設定を開く', exact: true })).toBeVisible();
});

test('mobile layout, navigation and composer remain usable', async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await newChat(page, request, 'モバイル');
  await page.getByRole('button', { name: 'メニュー', exact: true }).click();
  await expect(page.getByLabel('キャラクターを選択', { exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: '保存した会話' }).getByRole('button').first().click();
  await send(page, 'スマートフォンからこんにちは');
  await expect(page.getByTestId('message')).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByLabel('メッセージ', { exact: true })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath('mobile-chat.png'), fullPage: true });
});

test('slow model discovery cannot overwrite a newer provider selection', async ({ page, request }) => {
  await newChat(page, request, '切替競合');
  let release: () => void = () => {};
  let arrived: () => void = () => {};
  let finished: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  const started = new Promise<void>(resolve => { arrived = resolve; });
  const completed = new Promise<void>(resolve => { finished = resolve; });
  await page.route('**/providers/ollama/models', async route => {
    arrived(); await gate;
    try { await route.fulfill({ json: [{ id: 'obsolete-model', provider: 'ollama', display_name: null }] }); }
    finally { finished(); }
  });
  await page.getByRole('button', { name: 'モデル更新' }).click();
  await started;
  await page.getByLabel('Provider', { exact: true }).selectOption('local-test');
  await expect(page.getByLabel('モデル', { exact: true })).toHaveValue('test-small');
  release(); await completed;
  await expect(page.getByLabel('Provider', { exact: true })).toHaveValue('local-test');
  await expect(page.getByLabel('モデル', { exact: true })).toHaveValue('test-small');
  await send(page, '切り替えたモデルで会話');
  await expect(page.locator('.message.assistant')).toContainText('local-test / test-small');
});

test('summary excerpts route back to their original stored messages', async ({ page, request }) => {
  const id = await newChat(page, request, '要約確認');
  for (let i = 0; i < 10; i++) {
    const response = await request.post(`/conversations/${id}/chat`, {
      headers, data: { provider: 'ollama', model: 'test-small', user_input: `約束${i}を覚えてね` },
    });
    expect(response.status()).toBe(200);
  }
  await page.getByRole('button', { name: '履歴を再読込' }).click();
  await expect(page.getByTestId('message')).toHaveCount(20);
  await page.getByRole('button', { name: '会話の要約', exact: true }).click();
  const summary = page.getByRole('complementary', { name: '会話要約' });
  await expect(summary).toContainText('全文の意味をすべて保持するものではありません');
  await summary.getByRole('button', { name: /出典を見る/ }).first().click();
  await expect(page.locator('.message.highlighted')).toHaveCount(1);
  await expect(page.locator('.message.highlighted')).toBeInViewport();
});


test('draft chunks appear before the validated final response replaces them', async ({ page, request }) => {
  const id = await newChat(page, request, 'ストリーム確認');
  await page.getByLabel('モデル', { exact: true }).selectOption('stream-model');
  await page.getByLabel('メッセージ', { exact: true }).fill('逐次表示して');
  await page.getByRole('button', { name: '送信', exact: true }).click();

  const preview = page.getByTestId('draft-preview');
  await expect(preview).toBeVisible();
  await expect(preview).toContainText('少しずつ');
  await expect(preview).toContainText('未確定の下書き');

  await expect(page.getByTestId('message')).toHaveCount(2);
  await expect(preview).toHaveCount(0);
  await expect(page.locator('.message.assistant')).toContainText('少しずつ表示して、最後に確定するよ。');
  await expect(page.getByLabel('メッセージ', { exact: true })).toHaveValue('');
  expect(await stored(request, id)).toHaveLength(2);
});

test('Stop cancels the active provider stream without committing the turn', async ({ page, request }) => {
  const id = await newChat(page, request, '停止確認');
  await page.getByLabel('モデル', { exact: true }).selectOption('slow-stream');
  const input = page.getByLabel('メッセージ', { exact: true });
  await input.fill('途中で止める入力');
  await page.getByRole('button', { name: '送信', exact: true }).click();

  await expect(page.getByTestId('draft-preview')).toContainText('途中00');
  const stop = page.getByRole('button', { name: '停止', exact: true });
  await expect(stop).toBeEnabled();
  await stop.click();

  await expect(page.getByRole('alert')).toContainText('生成を停止しました');
  await expect(page.getByTestId('draft-preview')).toHaveCount(0);
  await expect(input).toHaveValue('途中で止める入力');
  await expect(page.getByRole('button', { name: '送信', exact: true })).toBeEnabled();
  expect(await stored(request, id)).toHaveLength(0);
});
