"""Constants used in the genome_dl package."""

# NCBI endpoints
DATASETS_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"
FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/genomes"

# NCBI Datasets API rate limits in requests per second (rps). The API allows
# 5 rps by default and 10 rps when a valid API key is supplied.
# https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/api-keys/
DATASETS_RATE_LIMIT = 5
DATASETS_RATE_LIMIT_WITH_KEY = 10

# Max accession bases per dataset_report POST body. Large --accessions files are
# chunked into batches of this size so a single oversized request is not sent.
ACCESSION_BATCH_SIZE = 1000

# Warn above this many concurrent FTP download workers. NCBI's file server has
# no published per-second limit, but many parallel connections strain it, so a
# high --cpus is flagged rather than silently allowed.
CPUS_WARN_THRESHOLD = 16

# Output naming
METADATA_SUFFIX = "-metadata.tsv"
SUMMARY_SUFFIX = "-summary.txt"
JSON_SUFFIX = ".json"

# User format -> (FTP source-name suffix, output extension).
# Verified against the live FTP assembly directory listing.
FORMATS = {
    "fasta": ("_genomic.fna.gz", "fna.gz"),
    "genbank": ("_genomic.gbff.gz", "gbff.gz"),
    "wgs": ("_wgsmaster.gbff.gz", "wgsmaster.gbff.gz"),
    "gff": ("_genomic.gff.gz", "gff.gz"),
    "gtf": ("_genomic.gtf.gz", "gtf.gz"),
    "protein": ("_protein.faa.gz", "faa.gz"),
    "genpept": ("_protein.gpff.gz", "gpff.gz"),
    "cds": ("_cds_from_genomic.fna.gz", "cds.fna.gz"),
    "translated-cds": ("_translated_cds.faa.gz", "translated_cds.faa.gz"),
    "rna": ("_rna_from_genomic.fna.gz", "rna.fna.gz"),
    "feature-table": ("_feature_table.txt.gz", "feature_table.txt.gz"),
    "assembly-report": ("_assembly_report.txt", "assembly_report.txt"),
    "assembly-stats": ("_assembly_stats.txt", "assembly_stats.txt"),
}

# User assembly level -> REST filters.assembly_level value.
ASSEMBLY_LEVELS = {
    "complete": "complete_genome",
    "chromosome": "chromosome",
    "scaffold": "scaffold",
    "contig": "contig",
}

# Metadata TSV column order (extracted from the Datasets dataset_report).
METADATA_COLUMNS = [
    "accession",
    "source_database",
    "assembly_name",
    "assembly_level",
    "assembly_status",
    "organism_name",
    "tax_id",
    "strain",
    "biosample",
    "bioproject",
    "submitter",
    "release_date",
    "refseq_category",
    "paired_accession",
    "total_sequence_length",
    "number_of_contigs",
    "contig_n50",
    "gc_percent",
    "files",
]
