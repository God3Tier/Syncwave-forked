use diesel::{
    pg::PgConnection,
    r2d2::{ConnectionManager, Pool},
};

pub type DbPool = Pool<ConnectionManager<PgConnection>>;

/// `DATABASE_URL` if set (local Compose), otherwise a libpq connection string
/// built from `DB_*`, so that in AWS the password can be injected on its own
/// from Secrets Manager. Diesel hands the string to libpq, which accepts both
/// forms.
pub fn database_url() -> String {
    database_url_from(|name| std::env::var(name).ok())
}

fn database_url_from(var: impl Fn(&str) -> Option<String>) -> String {
    if let Some(url) = var("DATABASE_URL").filter(|url| !url.is_empty()) {
        return url;
    }
    let setting = |name: &str, default: &str| var(name).unwrap_or_else(|| default.to_owned());
    [
        ("host", setting("DB_HOST", "localhost")),
        ("port", setting("DB_PORT", "5432")),
        ("dbname", setting("DB_NAME", "orchestrator")),
        ("user", setting("DB_USER", "orchestrator")),
        (
            "password",
            setting("DB_PASSWORD", "orchestrator_dev_password"),
        ),
    ]
    .iter()
    // libpq key='value': backslash and single quote are escaped with a backslash
    .map(|(key, value)| {
        format!(
            "{key}='{}'",
            value.replace('\\', "\\\\").replace('\'', "\\'")
        )
    })
    .collect::<Vec<_>>()
    .join(" ")
}

pub fn create_pool(database_url: &str) -> Result<DbPool, diesel::r2d2::PoolError> {
    let manager = ConnectionManager::<PgConnection>::new(database_url);
    Pool::builder().build(manager)
}

#[cfg(test)]
#[test]
#[ignore = "requires TEST_DATABASE_URL pointing to a disposable PostgreSQL database"]
fn creates_a_pool_and_checks_out_a_postgres_connection() {
    let database_url = std::env::var("TEST_DATABASE_URL")
        .expect("set TEST_DATABASE_URL to run this integration test");
    let pool = create_pool(&database_url).expect("database pool should initialize");
    let _connection = pool.get().expect("pool should provide a connection");
}

#[cfg(test)]
mod database_url_tests {
    use super::database_url_from;
    use std::collections::HashMap;

    fn lookup(vars: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let vars: HashMap<String, String> = vars
            .iter()
            .map(|(name, value)| (name.to_string(), value.to_string()))
            .collect();
        move |name| vars.get(name).cloned()
    }

    #[test]
    fn database_url_wins_over_db_variables() {
        let url = database_url_from(lookup(&[
            ("DATABASE_URL", "postgres://a:b@db:5432/orchestrator"),
            ("DB_HOST", "ignored"),
        ]));
        assert_eq!(url, "postgres://a:b@db:5432/orchestrator");
    }

    #[test]
    fn builds_a_libpq_string_from_db_variables() {
        let url = database_url_from(lookup(&[
            ("DB_HOST", "db.internal"),
            ("DB_PORT", "6543"),
            ("DB_NAME", "orchestrator"),
            ("DB_USER", "orchestrator"),
            ("DB_PASSWORD", r"it's\secret"),
        ]));
        assert_eq!(
            url,
            r"host='db.internal' port='6543' dbname='orchestrator' user='orchestrator' password='it\'s\\secret'"
        );
    }

    #[test]
    fn defaults_match_the_local_database() {
        let url = database_url_from(lookup(&[]));
        assert_eq!(
            url,
            "host='localhost' port='5432' dbname='orchestrator' user='orchestrator' password='orchestrator_dev_password'"
        );
    }
}
