import os
import json
import re
from mysql.connector.pooling import MySQLConnectionPool
from mysql.connector.connection import MySQLConnection


class ConnectionPool:
    def __init__(self) -> None:
        try:
            connstr_json: dict[str, str|int|bool] = json.loads(os.getenv("RPP2_CONNSTR", ""))
            self.pool: MySQLConnectionPool = MySQLConnectionPool(
                pool_size=2,
                pool_name=f"pool-{connstr_json.get('user', 'undefined')}",
                **connstr_json  # pyright: ignore[reportArgumentType]
            )
        except (json.JSONDecodeError, TypeError) as e:
            raise TypeError(
                re.sub(
                    r"\r?\n +", '\n',
                    """
                    Unable to parse environment variable 'RPP2_CONNSTR'. Please ensure this is set as
                    JSON in the format: '{"host": "mysql.server.hostname", "port": mysql_port_number, 
                    "user": "username", "password": "password", "database": "database name", 
                    "ssl_verify_cert": true/false, "ssl_ca": "/file/containing/the/SSL/certificate/authority.crt"}'
                    """
                ).strip()
            )

    def get_connection(self)-> MySQLConnection:
        return self.pool.get_connection()  # pyright: ignore[reportReturnType]


CONNECTION_POOL = ConnectionPool()


### example implementation
# with CONNECTION_POOL.get_connection() as conn:
#     cursor = conn.cursor()
#     cursor.execute("SELECT company_number FROM companies LIMIT 1")
#     print(cursor.fetchall())
#     conn.close()
