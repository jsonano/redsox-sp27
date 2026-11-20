-- Example queries for redsox.db
-- Retrieving data on Masataka Yoshida and Sonny Gray

-- Initial Command: python -m pipeline 2026-07-10 2026-07-12
-- (this is the BOS-NYM series)

-- retrieve names and IDs
SELECT full_name, player_id
FROM PLAYER
WHERE first_name IN ('Masataka', 'Sonny')
  AND last_name
    IN ('Yoshida', 'Gray');

-- returns whole game box scores for both players
-- note: since Yoshida is a batter, pitcher values are NULL.
--		 symmetrically holds for Gray.
SELECT *
FROM BOX_SCORE
WHERE player_id IN (SELECT player_id
                    FROM PLAYER
                    WHERE full_name in ('Masataka Yoshida', 'Sonny Gray'));

-- finding Yoshida's BA for the 3 games
SELECT ROUND((SUM(bat_h) * 1.0) / SUM(bat_ab), 3) AS bat_avg
FROM BOX_SCORE
WHERE player_id IN (SELECT player_id
                    FROM PLAYER
                    WHERE full_name = 'Masataka Yoshida');

-- finding Gray's total SOs
-- note: since pit_ip is in traditional format (5.1, 5.2), I calculate
--		 how many innings were actually pitched by dividing by 3
SELECT SUM(pit_so)                       AS total_so,
       ROUND(SUM(pit_so) / (SUM(pit_outs) / 3.0), 3) AS so_per_ip
FROM BOX_SCORE
WHERE player_id IN (SELECT player_id
                    FROM PLAYER
                    WHERE full_name = 'Sonny Gray');

-- finding all of BOS transactions but only include certain attributes
SELECT person_name, type_code, type_desc, description, date, effective_date
FROM TRANSACTIONS
WHERE from_team_name = "Boston Red Sox"
   OR to_team_name = "Boston Red Sox";
