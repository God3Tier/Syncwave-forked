# One small Postgres instance holding one database per service
# (plan.md section 11). Each service stack creates its own database and
# login role with modules/service-database. The master password is
# generated and kept in Secrets Manager by RDS itself.

resource "aws_db_subnet_group" "this" {
  name       = "syncwave"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "this" {
  identifier     = "syncwave"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  username                    = "syncwave_admin"
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false

  # Torn down after every session (RUNBOOK.md §8), so nothing is kept:
  # no automated backups (also skips the initial backup, so it starts faster)
  # and no final snapshot.
  backup_retention_period    = 0
  auto_minor_version_upgrade = true
  apply_immediately          = true
  skip_final_snapshot        = true
}
