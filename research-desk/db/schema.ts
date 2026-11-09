import { sqliteTable, text, integer, real } from "drizzle-orm/sqlite-core";
export const stocks = sqliteTable("desk_stocks", {
  ticker: text("ticker").primaryKey(), name: text("name").notNull(), addedAt: text("added_at").notNull(),
  snapshot: text("snapshot").notNull(), notes: text("notes").notNull().default(""),
  stage: text("stage").notNull().default("Watching"), manual: text("manual").notNull().default("{}"),
  research: text("research").notNull().default("{}"),
});
export const targetHistory = sqliteTable("target_history", {
  id: integer("id").primaryKey({ autoIncrement: true }), ticker: text("ticker").notNull(),
  recordedAt: text("recorded_at").notNull(), target: real("target").notNull(),
});
export const settings = sqliteTable("desk_settings", { key: text("key").primaryKey(), value: text("value").notNull() });
