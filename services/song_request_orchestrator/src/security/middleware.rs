use std::sync::Arc;

use actix_web::{
    Error, HttpMessage,
    dev::{Service, ServiceRequest, ServiceResponse, Transform, forward_ready},
    http::header,
};
use futures_util::future::LocalBoxFuture;

use crate::security::claims::CognitoClaims;
use crate::security::client::CognitoClient;
use crate::security::errors::AuthError;

/// Middleware factory that verifies Cognito JWTs on incoming requests
/// (a `Transform` in actix-web terms).
///
/// The middleware is registered on the app with
/// [`App::wrap`](actix_web::App::wrap):
///
/// ```ignore
/// App::new()
///     .wrap(CognitoAuth::new(cognito_client).exclude("/health"))
///     .configure(configure_routes)
/// ```
///
/// Every request that is not excluded must carry an
/// `Authorization: Bearer <token>` header. The token is verified against
/// Cognito's JWKS (signature, issuer, audience, expiration). On success the
/// verified [`CognitoClaims`] are stored in the request extensions, where
/// handlers pick them up as parameters through the [`UserId`] and
/// [`CognitoClaims`] extractors:
///
/// ```ignore
/// async fn handler(user_id: UserId) -> impl Responder {
///     HttpResponse::Ok().body(user_id.as_str())
/// }
/// ```
///
/// When no [`CognitoClient`] is configured (`None`) authentication is
/// disabled and every request passes through unauthenticated, which keeps
/// local development working.
///
/// [`UserId`]: crate::security::UserId
#[derive(Clone)]
pub struct CognitoAuth {
    client: Option<Arc<CognitoClient>>,
    exclude: Vec<String>,
}

impl CognitoAuth {
    pub fn new(client: Option<Arc<CognitoClient>>) -> Self {
        Self {
            client,
            exclude: Vec::new(),
        }
    }

    /// Exclude a path or path prefix from authentication (e.g. `"/health"`).
    pub fn exclude(mut self, path: impl Into<String>) -> Self {
        self.exclude.push(path.into());
        self
    }
}

// Two steps are involved in middleware processing:
// 1. middleware initialization: the factory (`Transform`) is called with the
//    next service in the chain as a parameter;
// 2. `Service::call` is invoked for every request.
impl<S, B> Transform<S, ServiceRequest> for CognitoAuth
where
    S: Service<ServiceRequest, Response = ServiceResponse<B>, Error = Error>,
    S::Future: 'static,
    B: 'static,
{
    type Response = ServiceResponse<B>;
    type Error = Error;
    type InitError = ();
    type Transform = CognitoAuthMiddleware<S>;
    type Future = std::future::Ready<Result<Self::Transform, Self::InitError>>;

    fn new_transform(&self, service: S) -> Self::Future {
        std::future::ready(Ok(CognitoAuthMiddleware {
            service,
            client: self.client.clone(),
            exclude: self.exclude.clone(),
        }))
    }
}

/// Service produced by [`CognitoAuth`]: verifies the request's bearer token,
/// stores the verified claims in the request extensions and then calls the
/// inner service.
pub struct CognitoAuthMiddleware<S> {
    service: S,
    client: Option<Arc<CognitoClient>>,
    exclude: Vec<String>,
}

impl<S, B> Service<ServiceRequest> for CognitoAuthMiddleware<S>
where
    S: Service<ServiceRequest, Response = ServiceResponse<B>, Error = Error>,
    S::Future: 'static,
    B: 'static,
{
    type Response = ServiceResponse<B>;
    type Error = Error;
    type Future = LocalBoxFuture<'static, Result<Self::Response, Self::Error>>;

    forward_ready!(service);

    fn call(&self, req: ServiceRequest) -> Self::Future {
        // No Cognito configuration, or a public path: hand the request to the
        // inner service unauthenticated.
        let excluded = self.is_excluded_for(&req);
        let Some(client) = self.client.as_deref().filter(|_| !excluded) else {
            let fut = self.service.call(req);
            return Box::pin(async move { fut.await });
        };

        // Authenticate before handing the request to the inner service so the
        // verified claims are stored in the request extensions.
        match authenticate(&req, client) {
            Ok(claims) => {
                req.extensions_mut().insert(claims);
            }
            Err(err) => return Box::pin(std::future::ready(Err(err))),
        }

        let fut = self.service.call(req);
        Box::pin(async move { fut.await })
    }
}

impl<S> CognitoAuthMiddleware<S> {
    /// Returns `true` if the request path is public.
    fn is_excluded_for(&self, req: &ServiceRequest) -> bool {
        let path = req.path();
        self.exclude
            .iter()
            .any(|prefix| path == prefix || path.starts_with(prefix))
    }
}

/// Extracts the bearer token from the request and verifies it.
fn authenticate(req: &ServiceRequest, client: &CognitoClient) -> Result<CognitoClaims, Error> {
    let header = req
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .ok_or_else(|| AuthError::MissingToken.into_actix_error())?;

    let token = header
        .strip_prefix("Bearer ")
        .ok_or_else(|| AuthError::InvalidHeader.into_actix_error())?;

    client
        .verify_token(token)
        .map_err(AuthError::into_actix_error)
}
