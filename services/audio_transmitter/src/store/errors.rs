use thiserror::Error;
use aws_sdk_s3::error::SdkError; 

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("Unable to retrieve s3bucket")]
    S3BucketError(
      Box<SdkError<
          aws_sdk_s3::operation::get_object::GetObjectError,
          aws_sdk_s3::config::http::HttpResponse,
      >>,
    ), 
    #[error("Unable to stream to bytes")]
    ByteStream(
      #[from]
      aws_smithy_types::byte_stream::error::Error
    )

}

impl From<
    SdkError<
        aws_sdk_s3::operation::get_object::GetObjectError,
        aws_sdk_s3::config::http::HttpResponse,
    >,
> for StoreError {
    fn from(
        err: SdkError<
            aws_sdk_s3::operation::get_object::GetObjectError,
            aws_sdk_s3::config::http::HttpResponse,
        >,
    ) -> Self {
        Self::S3BucketError(Box::new(err))
    }
}
