# Run only through the confined offline guard: RDS is untrusted.
# Arguments: result.rds, frozen assessment plan.json, export.json
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 3L)
plan <- jsonlite::fromJSON(args[[2]], simplifyVector = FALSE)
write_result <- function(x) jsonlite::write_json(x, args[[3]], auto_unbox = TRUE,
  null = 'null', na = 'null', digits = NA, pretty = TRUE)
if (!file.exists(args[[1]])) {
  write_result(list(status = 'output_unavailable', fidelity = 'unassessable'))
  quit(status = 0L)
}
x <- readRDS(args[[1]])
if (!is.data.frame(x)) {
  write_result(list(status = 'not_data_frame', object_class = class(x), fidelity = 'unassessable'))
  quit(status = 0L)
}
nm <- names(x)
if (anyDuplicated(nm)) {
  write_result(list(status = 'duplicate_column_names', schema = nm, fidelity = 'unassessable'))
  quit(status = 0L)
}
atomic <- vapply(x, function(z) is.atomic(z) && is.null(dim(z)), logical(1))
schema <- lapply(seq_along(nm), function(i) list(name = nm[i], class = class(x[[i]]),
  typeof = typeof(x[[i]]), atomic = atomic[i]))
fields <- unlist(plan$candidate_fields, use.names = FALSE)
keys <- unlist(plan$key, use.names = FALSE)
available <- intersect(fields, nm[atomic])
result <- list(status = 'schema_exported', object_class = class(x), row_count = nrow(x),
  schema = schema, fields_available = available, fields_unavailable = setdiff(fields, available),
  fidelity = 'unassessable', selected_matches = list())
# Selection must already have been independently frozen before candidate output inspection.
if (identical(plan$source_fixture_status, 'frozen') && length(plan$selected) && all(keys %in% available)) {
  result$selected_matches <- lapply(plan$selected, function(s) {
    hit <- rep(TRUE, nrow(x))
    for (k in keys) hit <- hit & !is.na(x[[k]]) & as.character(x[[k]]) == as.character(s[[k]])
    lapply(which(hit), function(i) {
      row <- lapply(available, function(k) {v <- x[[k]][i]; if (is.na(v)) NULL else unname(v)})
      names(row) <- available
      row
    })
  })
  result$status <- 'selected_rows_exported'
  result$fidelity <- 'comparison_pending'
}
write_result(result)
