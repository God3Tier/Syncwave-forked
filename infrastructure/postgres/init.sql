-- Database-per-service (plan.md §11 data ownership).
-- Each service gets its own database and login role, and cannot connect to
-- any other service's database: services share data through APIs and events,
-- never through each other's tables.
--
-- LOCAL DEVELOPMENT ONLY: every password equals the role name.
-- Production credentials come from AWS secrets, not from this file.
--
-- Postgres runs this script only when its data volume is first created.
-- To run it again: docker compose down -v && docker compose up -d
-- A service that does not need a database can simply ignore its database.

CREATE ROLE catalogue LOGIN PASSWORD 'catalogue';
CREATE DATABASE catalogue OWNER catalogue;
REVOKE CONNECT ON DATABASE catalogue FROM PUBLIC;

CREATE ROLE search LOGIN PASSWORD 'search';
CREATE DATABASE search OWNER search;
REVOKE CONNECT ON DATABASE search FROM PUBLIC;

CREATE ROLE streaming LOGIN PASSWORD 'streaming';
CREATE DATABASE streaming OWNER streaming;
REVOKE CONNECT ON DATABASE streaming FROM PUBLIC;

CREATE ROLE upload LOGIN PASSWORD 'upload';
CREATE DATABASE upload OWNER upload;
REVOKE CONNECT ON DATABASE upload FROM PUBLIC;

CREATE ROLE lyrics LOGIN PASSWORD 'lyrics';
CREATE DATABASE lyrics OWNER lyrics;
REVOKE CONNECT ON DATABASE lyrics FROM PUBLIC;

CREATE ROLE waveform LOGIN PASSWORD 'waveform';
CREATE DATABASE waveform OWNER waveform;
REVOKE CONNECT ON DATABASE waveform FROM PUBLIC;

CREATE ROLE playlist LOGIN PASSWORD 'playlist';
CREATE DATABASE playlist OWNER playlist;
REVOKE CONNECT ON DATABASE playlist FROM PUBLIC;

CREATE ROLE recommendation LOGIN PASSWORD 'recommendation';
CREATE DATABASE recommendation OWNER recommendation;
REVOKE CONNECT ON DATABASE recommendation FROM PUBLIC;

CREATE ROLE jam LOGIN PASSWORD 'jam';
CREATE DATABASE jam OWNER jam;
REVOKE CONNECT ON DATABASE jam FROM PUBLIC;

CREATE ROLE sync LOGIN PASSWORD 'sync';
CREATE DATABASE sync OWNER sync;
REVOKE CONNECT ON DATABASE sync FROM PUBLIC;
