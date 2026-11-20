CREATE CONSTRAINT account_id_unique IF NOT EXISTS FOR (n:Account) REQUIRE n.account_id IS UNIQUE;
CREATE CONSTRAINT device_id_unique IF NOT EXISTS FOR (n:Device) REQUIRE n.device_id IS UNIQUE;
CREATE CONSTRAINT ip_unique IF NOT EXISTS FOR (n:IP) REQUIRE n.ip IS UNIQUE;
CREATE CONSTRAINT label_account_unique IF NOT EXISTS FOR (n:Label) REQUIRE n.account_id IS UNIQUE;
CREATE CONSTRAINT transfer_id_unique IF NOT EXISTS FOR ()-[r:TRANSFERRED]-() REQUIRE r.txn_id IS UNIQUE;
CREATE RANGE INDEX transferred_ts IF NOT EXISTS FOR ()-[r:TRANSFERRED]-() ON (r.ts);
CALL db.awaitIndexes(120);
