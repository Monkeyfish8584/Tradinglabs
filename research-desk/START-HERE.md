# Ollie’s Research Desk in Cursor

Open `Tradinglabs.code-workspace` from the repository root in Cursor. Run research-desk terminal commands from this folder (`cd research-desk`). This source export comes from the published dashboard at commit `50619f6`. It includes the UI, market data providers, research logic, database migrations and public sample snapshots. The local database starts with the six sample tickers. The live watchlist and notes are stored separately in the hosted database.

## Run a local copy

Use Node.js 24 and the pnpm version pinned in `package.json`. Run these commands in Cursor’s terminal from the project folder. Apply the SQL files in order once per local database.

```sh
pnpm install --frozen-lockfile
pnpm build
pnpm exec wrangler d1 execute DB --config dist/server/wrangler.json --local --persist-to .wrangler/state --file drizzle/0000_woozy_loners.sql
pnpm exec wrangler d1 execute DB --config dist/server/wrangler.json --local --persist-to .wrangler/state --file drizzle/0001_old_zeigeist.sql
pnpm start
```

Open the local URL printed by Wrangler. For development with hot reload, use `pnpm dev` after applying the migrations. The app uses a local Cloudflare D1 database and reads public market data on demand.

## Starting prompt for Cursor

> Read START-HERE.md and README.md. Walk through the watchlist UI in `app/desk.tsx`, the API in `app/api/desk/route.ts`, and the research and market data code in `lib/`. Run the local dashboard and explain how those pieces fit together before making changes. Keep all development local unless I ask you to deploy.
