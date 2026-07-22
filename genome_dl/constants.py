"""Constants used in the genome_dl package."""

# NCBI endpoints
DATASETS_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"
FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/genomes"

# Defaults
DEFAULT_LIMIT = 10
DEFAULT_CPUS = 3
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_SLEEP = 10
DEFAULT_PREFIX = "genome-dl"
METADATA_SUFFIX = "-metadata.tsv"

# User format -> (FTP source-name suffix, output extension).
# Verified against the live FTP assembly directory listing.
FORMATS = {
    "fasta": ("_genomic.fna.gz", "fna.gz"),
    "genbank": ("_genomic.gbff.gz", "gbff.gz"),
    "gff": ("_genomic.gff.gz", "gff.gz"),
    "gtf": ("_genomic.gtf.gz", "gtf.gz"),
    "protein": ("_protein.faa.gz", "faa.gz"),
    "cds": ("_cds_from_genomic.fna.gz", "cds.fna.gz"),
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
