/* create the databases from a connection to postgres */
/* execute each CREATE DATABASE separately with autocommit enabled */
CREATE DATABASE comp9120_hotel
  WITH TEMPLATE template0
       ENCODING 'UTF8';

CREATE DATABASE comp9120_hotel_test
  WITH TEMPLATE template0
       ENCODING 'UTF8';

/* set the hotel time zone */
ALTER DATABASE comp9120_hotel
  SET timezone TO 'Australia/Sydney';

ALTER DATABASE comp9120_hotel_test
  SET timezone TO 'Australia/Sydney';
