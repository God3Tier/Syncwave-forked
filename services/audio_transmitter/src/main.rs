mod catalogue;
mod controller;
mod store;

use actix_web::{App, HttpServer, web};
use aws_sdk_s3::Client;
use aws_smithy_types::timeout::TimeoutConfig;
use catalogue::{Catalogue, HttpCatalogue};
use std::{env, io, sync::Arc, time::Duration};
use store::audio::AudioStore;

// pub type Error = Box<dyn std::error::Error + Send + Sync>;

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenvy::dotenv().ok();
    // Song metadata comes from the Catalogue Service; this service has no database.
    let catalogue_url = env::var("CATALOGUE_URL")
        .unwrap_or_else(|_| "http://localhost:8080/api/catalogue".to_owned());
    let catalogue_timeout = env::var("CATALOGUE_TIMEOUT_SECONDS")
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .filter(|seconds| *seconds > 0.0)
        .unwrap_or(3.0);
    let catalogue: Arc<dyn Catalogue> = Arc::new(
        HttpCatalogue::new(&catalogue_url, Duration::from_secs_f64(catalogue_timeout)).map_err(
            |error| io::Error::other(format!("failed to build the Catalogue client: {error}")),
        )?,
    );
    let catalogue = web::Data::new(catalogue);

    let config = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .timeout_config(
            TimeoutConfig::builder()
                .operation_timeout(Duration::from_secs(5))
                .operation_attempt_timeout(Duration::from_millis(1500))
                .build(),
        )
        .load()
        .await;
    // Path-style URLs also work with the local S3-compatible store's Docker hostname.
    let s3_client = Client::from_conf(
        aws_sdk_s3::config::Builder::from(&config)
            .force_path_style(true)
            .build(),
    );
    let bucket_name = env::var("S3_BUCKET").unwrap_or_else(|_| "syncwave-audio".to_owned());

    // TODO: Set the cache to be configurable
    let store = web::Data::new(AudioStore::new(10_000, s3_client, bucket_name));

    HttpServer::new(move || {
        App::new()
            .app_data(store.clone())
            .app_data(catalogue.clone())
            .configure(controller::configure_routes)
    })
    .bind(("0.0.0.0", 8081))?
    .run()
    .await
}
