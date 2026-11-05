use crate::catalogue::{Catalogue, CatalogueError};
use actix_web::{HttpResponse, Responder, web};
use serde::Serialize;
use std::sync::Arc;
use uuid::Uuid;

#[derive(Serialize)]
struct StreamInfo {
    song_id: Uuid,
    stream_url: String,
    supports_ranges: bool,
    manifest_url: String,
}

pub async fn get_stream_info(
    catalogue: web::Data<Arc<dyn Catalogue>>,
    song_id: web::Path<Uuid>,
) -> impl Responder {
    let song_id = song_id.into_inner();
    let song = match catalogue.get_song(song_id).await {
        Ok(song) => song,
        Err(CatalogueError::NotFound) => return HttpResponse::NotFound().finish(),
        Err(error) => return HttpResponse::BadGateway().body(error.to_string()),
    };

    if song.processing_status != "READY" {
        return HttpResponse::Conflict().body("the song is not ready for streaming");
    }

    HttpResponse::Ok().json(StreamInfo {
        song_id,
        stream_url: format!("/api/streaming/tracks/{song_id}/audio"),
        supports_ranges: false,
        manifest_url: format!("/api/streaming/tracks/{song_id}/manifest"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalogue::SongInfo;
    use actix_web::{App, http::StatusCode, test};

    struct FakeCatalogue;

    #[async_trait::async_trait]
    impl Catalogue for FakeCatalogue {
        async fn get_song(&self, song_id: Uuid) -> Result<SongInfo, CatalogueError> {
            Ok(SongInfo {
                song_id,
                audio_reference: format!("audio/{song_id}.mp3"),
                duration_ms: Some(120_000),
                processing_status: "READY".into(),
            })
        }
    }

    #[actix_web::test]
    async fn returns_the_browser_facing_stream_url() {
        let song_id = Uuid::new_v4();
        let catalogue: Arc<dyn Catalogue> = Arc::new(FakeCatalogue);
        let app = test::init_service(App::new().app_data(web::Data::new(catalogue)).route(
            "/tracks/{track_id}/stream-info",
            web::get().to(get_stream_info),
        ))
        .await;

        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/tracks/{song_id}/stream-info"))
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
        let body: serde_json::Value = test::read_body_json(response).await;
        assert_eq!(body["song_id"], song_id.to_string());
        assert_eq!(
            body["stream_url"],
            format!("/api/streaming/tracks/{song_id}/audio")
        );
        assert_eq!(body["supports_ranges"], false);
        assert_eq!(
            body["manifest_url"],
            format!("/api/streaming/tracks/{song_id}/manifest")
        );
    }
}
