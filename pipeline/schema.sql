-- SQLite Database Schema --

-- TEAM --
CREATE TABLE IF NOT EXISTS TEAM (
    team_id            INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    abbreviation       TEXT,
    team_name          TEXT,
    location_name      TEXT,
    league_id          INTEGER,   -- MLB league
    league_name        TEXT,
    division_id        INTEGER,
    division_name      TEXT,
    venue_id           INTEGER,
    venue_name         TEXT,
    first_year_of_play INTEGER,
    season             INTEGER,
    active             INTEGER
);

-- PLAYER --
CREATE TABLE IF NOT EXISTS PLAYER (
    player_id        INTEGER PRIMARY KEY,
    full_name        TEXT NOT NULL,
    first_name       TEXT,
    last_name        TEXT,
    birth_date       TEXT,
    birth_country    TEXT,
    height_inches    INTEGER,
    weight           INTEGER,
    primary_position TEXT,
    bat_side         TEXT,
    pitch_hand       TEXT,
    mlb_debut_date   TEXT,
    active           INTEGER
);

-- SCHEDULE --
CREATE TABLE IF NOT EXISTS SCHEDULE (
    game_pk           INTEGER PRIMARY KEY,
    official_date     TEXT NOT NULL,
    game_datetime_utc TEXT,
    season            INTEGER,
    game_type         TEXT,
    status_code       TEXT,
    status_detail     TEXT,
	-- home team
    home_team_id      INTEGER REFERENCES TEAM(team_id),
    home_team_name    TEXT,
    home_score        INTEGER,  -- NULL until played
    home_is_winner    INTEGER,
    home_wins         INTEGER,  -- record after game
    home_losses       INTEGER,
	-- away team
    away_team_id      INTEGER REFERENCES TEAM(team_id),
    away_team_name    TEXT,
    away_score        INTEGER,
    away_is_winner    INTEGER,
    away_wins         INTEGER,
    away_losses       INTEGER,
    venue_id          INTEGER,
    venue_name        TEXT,
    double_header     TEXT,
    game_number       INTEGER,
    day_night         TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_date ON SCHEDULE(official_date);

-- BOX_SCORE --
CREATE TABLE IF NOT EXISTS BOX_SCORE (
    game_pk            INTEGER NOT NULL REFERENCES SCHEDULE(game_pk),
    player_id          INTEGER NOT NULL REFERENCES PLAYER(player_id),
    team_id            INTEGER REFERENCES TEAM(team_id),
    is_home            INTEGER,
    position           TEXT,
    batting_order      INTEGER,
    -- batting (NULL if the player did not bat)
    bat_ab             INTEGER,
    bat_r              INTEGER,
    bat_h              INTEGER,
    bat_doubles        INTEGER,
    bat_triples        INTEGER,
    bat_hr             INTEGER,
    bat_rbi            INTEGER,
    bat_bb             INTEGER,
    bat_so             INTEGER,
    bat_sb             INTEGER,
    -- pitching (NULL if the player did not pitch)
    pit_ip             TEXT,     -- ie. "5.1"
    pit_outs           INTEGER,
    pit_batters_faced  INTEGER,
    pit_h              INTEGER,
    pit_r              INTEGER,
    pit_er             INTEGER,
    pit_bb             INTEGER,
    pit_so             INTEGER,
    pit_hr             INTEGER,
    pit_pitches        INTEGER,
    pit_strikes        INTEGER,
    -- Statcast for pitchers, added last after BOX_SCORE and PITCH have been compiled first
    sc_avg_velo        REAL,
    sc_max_velo        REAL,
    sc_avg_spin        REAL,
    sc_whiffs          INTEGER,
    sc_called_strikes  INTEGER,
    PRIMARY KEY (game_pk, player_id)
);

-- PITCH --
CREATE TABLE IF NOT EXISTS PITCH (
    -- game (game_pk + at_bat_number + pitch_number identify the pitch)
    game_pk                         INTEGER NOT NULL REFERENCES SCHEDULE(game_pk),
    game_date                       TEXT,
    at_bat_number                   INTEGER NOT NULL,
    pitch_number                    INTEGER NOT NULL,  -- pitch number within the at-bat
    inning                          INTEGER,
    inning_topbot                   TEXT,              -- Top / Bot
    home_score                      INTEGER,           -- score before the pitch
    away_score                      INTEGER,
    -- pitcher
    pitcher_id                      INTEGER REFERENCES PLAYER(player_id),
    p_throws                        TEXT,              -- L / R
    -- batter
    batter_id                       INTEGER REFERENCES PLAYER(player_id),
    stand                           TEXT,              -- L / R
    -- count before pitch
    balls                           INTEGER,
    strikes                         INTEGER,
    outs_when_up                    INTEGER,
    -- pitch: type, velocity, spin, release point, movement
    pitch_type                      TEXT,              -- ie. FF, SL
    pitch_name                      TEXT,              -- ie. 4-Seam Fastball
    release_speed                   REAL,              -- mph
    effective_speed                 REAL,              -- mph, adjusted for extension
    release_spin_rate               REAL,              -- rpm
    spin_axis                       REAL,              -- degrees
    release_extension               REAL,              -- ft
    release_pos_x                   REAL,              -- ft
    release_pos_z                   REAL,              -- ft
    pfx_x                           REAL,              -- horizontal movement, ft
    pfx_z                           REAL,              -- vertical movement, ft
    -- location (as the pitch crosses the plate)
    plate_x                         REAL,              -- ft from center of plate
    plate_z                         REAL,              -- ft above the ground
    zone                            INTEGER,           -- 1-9 strike zone, 11-14 outside
    sz_top                          REAL,              -- batter's strike zone top, ft
    sz_bot                          REAL,              -- batter's strike zone bottom, ft
    -- result
    type                            TEXT,              -- B / S / X (ball, strike, in play)
    description                     TEXT,              -- ie. called_strike, swinging_strike
    events                          TEXT,              -- plate appearance result, last pitch only
    des                             TEXT,              -- play-by-play text
    delta_run_exp                   REAL,              -- run value of the pitch
    -- swing
    bat_speed                       REAL,              -- mph
    swing_length                    REAL,              -- ft
    -- batted ball (NULL unless the ball was put in play)
    bb_type                         TEXT,              -- ground_ball, line_drive, fly_ball, popup
    launch_speed                    REAL,              -- exit velocity, mph
    launch_angle                    REAL,              -- degrees
    hit_distance_sc                 REAL,              -- ft
    estimated_ba_using_speedangle   REAL,              -- xBA
    estimated_woba_using_speedangle REAL,              -- xwOBA
    PRIMARY KEY (game_pk, at_bat_number, pitch_number)
);
CREATE INDEX IF NOT EXISTS idx_pitch_pitcher ON PITCH(pitcher_id);
CREATE INDEX IF NOT EXISTS idx_pitch_batter  ON PITCH(batter_id);

-- TRANSACTIONS --
CREATE TABLE IF NOT EXISTS TRANSACTIONS (
    row_id          INTEGER PRIMARY KEY,
    transaction_id  INTEGER NOT NULL,
    person_id       INTEGER,   -- NULL for cash-only transactions (no player trader)
    person_name     TEXT,
    type_code       TEXT,
    type_desc       TEXT,
    description     TEXT,
    date            TEXT NOT NULL,
    effective_date  TEXT,
    resolution_date TEXT,
    from_team_id    INTEGER,   -- often a minor-league team not in TEAM, so name is kept too
    from_team_name  TEXT,
    to_team_id      INTEGER,
    to_team_name    TEXT
);
CREATE INDEX IF NOT EXISTS idx_transactions_person ON TRANSACTIONS(person_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date   ON TRANSACTIONS(date);
