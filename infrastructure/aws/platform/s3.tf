# The audio bucket (syncwave-audio locally). Upload writes audio/ and
# lyrics/ objects; Streaming, Lyrics and Waveform read them with their task
# roles. Bucket names are global, so the account ID is part of the name.

resource "aws_s3_bucket" "audio" {
  bucket        = "syncwave-audio-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.audio_bucket_force_destroy
}

resource "aws_s3_bucket_public_access_block" "audio" {
  bucket                  = aws_s3_bucket.audio.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "audio" {
  bucket = aws_s3_bucket.audio.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
