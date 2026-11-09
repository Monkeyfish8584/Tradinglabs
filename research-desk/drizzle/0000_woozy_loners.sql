CREATE TABLE `desk_settings` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `desk_stocks` (
	`ticker` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`added_at` text NOT NULL,
	`snapshot` text NOT NULL,
	`notes` text DEFAULT '' NOT NULL,
	`stage` text DEFAULT 'Watching' NOT NULL,
	`manual` text DEFAULT '{}' NOT NULL
);
--> statement-breakpoint
CREATE TABLE `target_history` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`ticker` text NOT NULL,
	`recorded_at` text NOT NULL,
	`target` real NOT NULL
);
