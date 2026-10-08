create database if not exists fusionpilot
  default character set utf8mb4
  collate utf8mb4_0900_ai_ci;

-- 改成一个自己的口令，并与后端启动时设置的 FUSIONPILOT_DB_PASSWORD 保持一致。
create user if not exists 'fusionpilot'@'localhost'
  identified by 'CHANGE_ME';

grant all privileges on fusionpilot.* to 'fusionpilot'@'localhost';

flush privileges;

use fusionpilot;

show tables;