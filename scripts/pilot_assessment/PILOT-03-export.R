# Run only in a confined offline session; input RDS is untrusted.
# Arguments: result.rds assessment-plan.json export.json
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==3L)
plan <- jsonlite::fromJSON(args[[2]], simplifyVector=FALSE)
x <- readRDS(args[[1]])
if (!is.data.frame(x)) { jsonlite::write_json(list(status='not_data_frame',object_class=class(x),row_count=NULL,schema=list()),args[[3]],auto_unbox=TRUE,null='null',pretty=TRUE); quit(status=2) }
# Use only ordinary atomic columns, never evaluate nested values.
nm <- names(x)
# Source mapping is identity: pinned get_places/parse_request preserves names.
# Numeric value and interval columns are explicitly coerced to numeric.
if (anyDuplicated(nm)) { jsonlite::write_json(list(status='duplicate_names',row_count=nrow(x),schema=nm),args[[3]],auto_unbox=TRUE,pretty=TRUE); quit(status=2) }
atomic <- vapply(x, function(z) is.atomic(z) && is.null(dim(z)), logical(1))
keys <- unlist(plan$key)
schema <- lapply(seq_along(nm), function(i) list(name=nm[i], class=class(x[[i]]), typeof=typeof(x[[i]]), atomic=atomic[i]))
if (!all(keys %in% nm) || !all(atomic[match(keys,nm)])) { jsonlite::write_json(list(status='keys_unavailable',row_count=nrow(x),object_class=class(x),schema=schema),args[[3]],auto_unbox=TRUE,null='null',pretty=TRUE); quit(status=2) }
fields <- c(keys,'data_value','data_value_unit','low_confidence_limit','high_confidence_limit','data_value_footnote_symbol','data_value_footnote')
fields <- intersect(fields,nm[atomic])
selected <- plan$selected
matches <- lapply(selected, function(s) {
  hit <- rep(TRUE,nrow(x))
  for (k in keys) hit <- hit & !is.na(x[[k]]) & as.character(x[[k]]) == as.character(s[[k]])
  inds <- which(hit)
  lapply(inds, function(i) {
    row <- lapply(fields, function(k) {v <- x[[k]][i]; if (is.na(v)) NULL else unname(v)})
    names(row) <- fields; row
  })
})
schema <- lapply(seq_along(nm), function(i) list(name=nm[i], class=class(x[[i]]), typeof=typeof(x[[i]]), atomic=atomic[i]))
res <- list(status='exported',row_count=nrow(x), object_class=class(x), schema=schema, fields_exported=fields, selected_matches=matches)
jsonlite::write_json(res,args[[3]],auto_unbox=TRUE,null='null',na='null',digits=NA,pretty=TRUE)
