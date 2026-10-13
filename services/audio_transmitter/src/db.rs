use diesel::{
    pg::PgConnection,
    prelude::*,
    r2d2::{ConnectionManager, Pool},
};

pub type DbPool = Pool<ConnectionManager<PgConnection>>;

pub fn create_pool(database_url: &str) -> Result<DbPool, diesel::r2d2::PoolError> {
    let manager = ConnectionManager::<PgConnection>::new(database_url);
    Pool::builder().build(manager)
}

/// Creates the music metadata table if it does not exist yet.
pub fn initialize_schema(pool: &DbPool) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut connection = pool.get()?;
    diesel::sql_query(include_str!(
        "../migrations/2026-10-09-000001_create_music_metadata/up.sql"
    ))
    .execute(&mut connection)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn creates_a_pool_and_checks_out_a_postgres_connection() {
        dotenvy::dotenv().ok();
        let database_url = std::env::var("TEST_DATABASE_URL")
            .expect("set TEST_DATABASE_URL to run this integration test");
        let pool = create_pool(&database_url).expect("database pool should initialize");
        let _connection = pool.get().expect("pool should provide a connection");
    }
}
