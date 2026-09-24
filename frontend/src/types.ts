/** Public HTTP DTOs. Source of truth: backend models.py and api.py. */
export const listFields = [
  'speech_style', 'personality', 'values', 'likes', 'dislikes', 'background',
  'lore', 'forbidden', 'relationship', 'response_style',
] as const;
export type ListField = typeof listFields[number];
export type CharacterInput = Record<ListField, string[]> & {
  name: string;
  first_person: string | null;
  second_person: string | null;
};
export type Character = CharacterInput & { id: string };
export interface Conversation { id: string; character_id: string; revision: number }
export interface Model { id: string; provider: string; display_name: string | null }
export interface Message {
  id: string;
  position: number;
  role: 'system' | 'user' | 'assistant';
  content: string;
  provider: string | null;
  model: string | null;
}
export interface Summary {
  strategy: string;
  covered_messages: number;
  through_position: number;
  entries: { source_message_id: string; position: number; role: string; excerpt: string }[];
}
export interface ChatResult {
  conversation_id: string;
  provider: string;
  model: string;
  text: string;
  guardian: { passed: boolean };
  repaired: boolean;
  regenerated_for_recall: boolean;
}

export type GenerationPhase = 'generating' | 'checking' | 'secondary_recall' | 'repairing';
export type ChatStreamEvent =
  | { type: 'started'; generation_id: string }
  | { type: 'phase'; generation_id: string; phase: GenerationPhase }
  | { type: 'draft_delta'; generation_id: string; text: string }
  | { type: 'final'; generation_id: string; result: ChatResult }
  | { type: 'stopped'; generation_id: string; status: 'stopped' }
  | { type: 'error'; generation_id: string; code: string; message: string; evaluation_id?: string };
