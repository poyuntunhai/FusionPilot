create database if not exists fusionpilot
  default character set utf8mb4
  collate utf8mb4_0900_ai_ci;

create user if not exists 'fusionpilot'@'localhost'
  identified by 'fusionpilot123';

grant all privileges on fusionpilot.* to 'fusionpilot'@'localhost';

flush privileges;

use fusionpilot;

show tables;