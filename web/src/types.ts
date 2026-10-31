export interface AgentFrame {
  loc: string;
  energy: number;
  inv: Record<string, number>;
  caches: Record<string, Record<string, number>>;
}

export interface EventRec {
  actor: string;
  action: string;
  ok: boolean;
  reason: string;
  location: string;
  data: Record<string, any>;
  public: Record<string, any>;
  seen_by: string[];
  victim: string | null;
}

export interface MessageRec {
  tick: number;
  sender: string;
  channel: string; // "group" | "dm:<Name>"
  text: string;
}

export interface Frame {
  tick: number;
  day: number;
  phase: string;
  agents: Record<string, AgentFrame>;
  raft: Record<string, number>;
  stockpile: Record<string, number>;
  wreck_gold_left: number;
  events: EventRec[];
  messages: MessageRec[];
  thoughts: Record<string, string>;
  reflections: Record<string, string>;
  god?: { type: string; targets: any; params: Record<string, any>; description: string; failed?: boolean }[];
}

export interface Persona {
  name: string;
  pronouns: string;
  color: string;
  accessory: string;
  age: number;
  background: string;
}

export interface Replay {
  version: number;
  run: { id: number; label: string; seed: number; ticks: number; parent_id: number | null; fork_tick: number | null };
  scenario: {
    phases: string[];
    days: number;
    raft_seats: number;
    recipe: Record<string, { resource: string; need: number }>;
    locations: string[];
  };
  personas: Persona[];
  beliefs: Record<string, Record<string, { trust: Record<string, number>; suspicions: Record<string, string>; facts: string[] }>>;
  report: any | null;
  frames: Frame[];
}
