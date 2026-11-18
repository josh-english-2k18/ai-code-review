import os

class ReviewConfig:
    """Central configuration for risk paths and exclusions."""

    # Paths that should trigger extra scrutiny in reviews
    RISK_PATHS = {
        'auth/', 'security/', 'payment/', 'crypto/', 'secrets/', 
        'migrations/', 'schemas/', 'models/', 'infrastructure/',
        '.github/workflows/', 'Dockerfile', 'docker-compose'
    }

    # Diff content patterns that should raise attention (regex)
    RISKY_DIFF_PATTERNS = [
        (r'\beval\s*\(', "Use of eval can introduce code injection risk."),
        (r'\bexec\s*\(', "Use of exec can execute arbitrary code."),
        (r'child_process|subprocess', "Spawning subprocesses can introduce security risks."),
        (r'dangerouslySetInnerHTML|innerHTML\s*=', "Direct HTML injection requires strict sanitization."),
        (r'\bchmod\s+777\b', "Overly permissive file permissions."),
        (r'\brm\s+-rf\b', "Destructive delete commands should be carefully reviewed."),
        (r'\bSELECT\b.+\bFROM\b.+\bWHERE\b', "Raw SQL detected; ensure parameterization."),
    ]

    # Files that should NEVER be included in a review packet
    CORE_EXCLUSIONS = {
        '.env', 'credentials', 'secrets.json',
    }

    EXCLUDED_DIR_NAMES = {
        '.git', '.ai_review', 'node_modules', '__pycache__',
        'venv', '.venv', 'dist', 'build', 'out', '.next',
    }

    BINARY_EXTENSIONS = {
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.icns',
        '.pdf', '.zip', '.jar', '.exe', '.dll', '.so', '.dylib',
        '.mp4', '.mp3', '.mov', '.avi', '.wav', '.wasm',
        '.woff', '.woff2', '.ttf', '.otf',
    }

    TEST_PATH_HINTS = (
        'tests/', '__tests__/', '.spec.', '.test.', 'test_',
    )

    DOC_PATH_HINTS = (
        'README', 'docs/', '.md', 'CHANGELOG', 'CONTRIBUTING',
    )

    IMPORT_ALIASES = {
        "@/": "src/",
        "@nilo/": "packages/",
    }

    DEFAULT_DIFF_CONTEXT_LINES = 3
    MAX_DIFF_LINES = 4000
    MAX_DIFF_PREVIEW_CHARS = 250_000
    MAX_HUNK_INDEX = 100
    MAX_UNTRACKED_LINES = 400
    MAX_UNTRACKED_BYTES = 1_000_000
    MAX_CONTEXT_FILES = 40
    MAX_IMPORTS_IN_SUMMARY = 8
    MAX_IMPACT_PER_FILE = 25

    @classmethod
    def is_risk_path(cls, file_path: str) -> bool:
        """Check if a file path is considered high-risk."""
        return any(file_path.startswith(risk) or risk in file_path for risk in cls.RISK_PATHS)

    @classmethod
    def is_binary_path(cls, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        return ext.lower() in cls.BINARY_EXTENSIONS

    @classmethod
    def is_test_path(cls, file_path: str) -> bool:
        path = file_path.lower()
        return any(hint in path for hint in cls.TEST_PATH_HINTS)

    @classmethod
    def is_doc_path(cls, file_path: str) -> bool:
        name = file_path.lower()
        return any(hint.lower() in name for hint in cls.DOC_PATH_HINTS)

    @classmethod
    def should_exclude(cls, file_path: str) -> bool:
        """Check if a file should be excluded regardless of git status."""
        *directories, filename = file_path.lower().split('/')
        return (
            not cls.EXCLUDED_DIR_NAMES.isdisjoint(directories)
            or any(part in cls.CORE_EXCLUSIONS or part.startswith('.env.')
                   or part.endswith(('.pem', '.key')) for part in (*directories, filename))
        )
