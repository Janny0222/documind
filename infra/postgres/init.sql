-- Runs once when the local Docker volume is first created.
-- A separate database for the automated test suite so tests never touch dev data.
CREATE DATABASE documind_test OWNER documind;
