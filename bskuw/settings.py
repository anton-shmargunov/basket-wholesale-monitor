"""MySQL credentials from Streamlit secrets."""


class SecretsError(Exception):
    """Raised when .streamlit/secrets.toml is missing or incomplete."""


def mysql_settings():
    """Read the [mysql] section. The password stays in secrets.toml."""
    try:
        import streamlit as st

        mysql = st.secrets["mysql"]
    except Exception as exc:
        raise SecretsError(
            "MySQL credentials are missing. Copy .streamlit/secrets.toml.example "
            "to .streamlit/secrets.toml and set host, port, user, password, and database."
        ) from exc

    missing = [key for key in ("host", "user", "password") if not str(mysql.get(key, "")).strip()]
    if missing:
        raise SecretsError("MySQL secrets are missing: " + ", ".join(missing))

    return {
        "host": str(mysql["host"]),
        "port": int(mysql.get("port", 3306)),
        "user": str(mysql["user"]),
        "password": str(mysql["password"]),
        "database": str(mysql.get("database", "clear_data")),
    }


def mysql_settings_or_none():
    try:
        return mysql_settings()
    except SecretsError:
        return None
