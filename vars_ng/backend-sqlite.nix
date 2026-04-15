{ lib, config, pkgs, ... }:
let
  cfg = config.vars.backend-sqlite;
  sqlite3 = "${pkgs.sqlite}/bin/sqlite3";
  initDb = "${sqlite3} ${cfg.database} 'CREATE TABLE IF NOT EXISTS vars (gen TEXT, file TEXT, content BLOB, PRIMARY KEY(gen, file));'";
in
{
  options.vars.backend-sqlite = {
    enable = lib.mkEnableOption "Use the SQLite backend for storing variables.";
    database = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/vars-ng/vars.db";
      description = "The path to the SQLite database file.";
    };
    vars = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "A list of variables to be stored in the SQLite backend.";
    };
  };

  config = lib.mkIf cfg.enable {
    vars.backends.sqlite = {
      get = ''
        ${initDb}
        ${sqlite3} ${cfg.database} "SELECT writefile('$out', content) FROM vars WHERE gen='$1' AND file='$2';" > /dev/null
      '';
      set = ''
        mkdir -p $(dirname ${cfg.database})
        ${initDb}
        ${sqlite3} ${cfg.database} "INSERT OR REPLACE INTO vars (gen, file, content) VALUES ('$1', '$2', readfile('$in'));"
      '';
      exists = ''
        ${initDb}
        count=$(${sqlite3} ${cfg.database} "SELECT COUNT(*) FROM vars WHERE gen='$1' AND file='$2';")
        test "$count" -eq 1
      '';
      delete = ''
        ${initDb}
        ${sqlite3} ${cfg.database} "DELETE FROM vars WHERE gen='$1' AND file='$2';"
      '';
      list = ''
        if [ -f ${cfg.database} ]; then
          ${initDb}
          ${sqlite3} -noheader -list ${cfg.database} "SELECT gen || '/' || file FROM vars;"
        fi
      '';
      generators = lib.genAttrs cfg.vars (_: { });
    };
  };
}
