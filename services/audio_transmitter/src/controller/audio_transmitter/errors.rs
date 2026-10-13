use thiserror::Error;

#[derive(Debug, Error)]
pub enum MetadataError {
	#[error("database connection failed: {0}")]
    Connection(#[from] r2d2::Error),
    
    #[error("metadata query failed: {0}")]
    Query(#[from] diesel::result::Error),
}
