args <- commandArgs(trailingOnly=TRUE)
urls <- switch(args[[1]],
  '06'=c('https://ephtracking.cdc.gov:443/apigateway/api/v1/measuresearch','https://ephtracking.cdc.gov:443/apigateway/api/v1/geographicTypes/99'),
  '07'=c('https://zenodo.org/records/18332002/files/t_category.csv?download=1','https://zenodo.org/records/18332002/files/t_factor.csv?download=1'), stop('invalid case'))
for (i in seq_along(urls)) {
 result <- tryCatch({
  response <- httr::GET(urls[[i]], httr::timeout(45), httr::config(maxfilesize=8*1024*1024, maxredirs=0))
  f <- tempfile(); writeBin(response$content, f); hash <- strsplit(system2('/usr/bin/sha256sum', f, stdout=TRUE), ' ')[[1]][1]; unlink(f)
  list(sequence=i,status=response$status_code,bytes=length(response$content),sha256=hash)
 }, error=function(e) list(sequence=i,status=NULL,bytes=NULL,sha256=NULL,error='request_failed'))
 cat(jsonlite::toJSON(result,auto_unbox=TRUE,null='null'), '\n')
}
