import helpers


def main():
    with helpers.CONNECTION_POOL.get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
                       SELECT fh.id,
                              pdf_url
                       FROM filing_history fh
                                LEFT JOIN filing_types ft ON fh.filing_type = ft.id

                       WHERE ft.name in ('AA', 'AA01', 'AA03', 'AAMD')
                         AND pdf_url LIKE '%format=pdf%'
                       """)

        rows = cursor.fetchmany(5000)

        while rows:
            for row in rows:
                # Process each row
                pass
            rows = cursor.fetchmany(5000)


if __name__ == "__main__":
    main()
