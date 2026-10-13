mod webhook;
mod controller;
mod db;
mod ringbuffer;
mod security; 

pub type Error = Box<dyn std::error::Error + Send + Sync>;
use actix_web::{App, HttpServer, web};
use std::{env, io};

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenvy::dotenv().ok();
    let database_url = env::var("DATABASE_URL").unwrap_or_else(|_| {
        "postgres://orchestrator:orchestrator_dev_password@localhost:5432/orchestrator".to_owned()
    });
    let pool = db::create_pool(&database_url)
        .map_err(|error| io::Error::other(format!("failed to create database pool: {error}")))?;
    let pool = web::Data::new(pool);

    HttpServer::new(move || {
        App::new()
            .app_data(pool.clone())
            .configure(controller::configure_routes)
    })
    .bind(("0.0.0.0", 8080))?
    .run()
    .await
}
