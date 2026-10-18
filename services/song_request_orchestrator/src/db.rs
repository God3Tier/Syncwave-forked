use diesel::{
    pg::PgConnection,
    r2d2::{ConnectionManager, Pool},
};

pub type DbPool = Pool<ConnectionManager<PgConnection>>;

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
