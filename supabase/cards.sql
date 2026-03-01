-- cards table: stores stock screener data for iOS app
-- Run this in Supabase SQL Editor

CREATE TABLE cards (
  id         bigserial PRIMARY KEY,
  tab        text NOT NULL,
  ticker     text NOT NULL,
  name       text NOT NULL,
  market_cap double precision NOT NULL DEFAULT 0,
  beta       double precision,
  trailing_pe      double precision,
  trailing_eps     double precision,
  earnings_date    bigint,
  forward_dividend_rate  double precision,
  forward_dividend_yield double precision,
  target_mean_price      double precision,
  periods    jsonb NOT NULL DEFAULT '{}'::jsonb,
  signal_overlay jsonb,
  reference_date date NOT NULL,
  sort_order int NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(tab, ticker)
);

ALTER TABLE cards ENABLE ROW LEVEL SECURITY;
CREATE POLICY "anon_read" ON cards FOR SELECT USING (true);
