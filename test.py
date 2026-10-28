# with helpers.CONNECTION_POOL.get_connection() as conn:
#     cursor = conn.cursor()
#     cursor.execute("SELECT company_number FROM companies LIMIT 1")
#     print(cursor.fetchall())
#
#     cursor.execute("SELECT company_number FROM companies WHERE incorporated_on < %s LIMIT 1", ('2020-01-01',))
#     print(cursor.fetchall())
