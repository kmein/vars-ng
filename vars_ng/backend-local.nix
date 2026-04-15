{ lib, config, ... }:
let
  cfg = config.vars.backend-local;
in
{
  options.vars.backend-local = {
    enable = lib.mkEnableOption "Use the local backend for storing variables.";
    directory = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/vars-ng";
      description = "The directory where the local backend will store variables.";
    };
    vars = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "A list of variables to be stored in the local backend.";
    };
  };

  config = lib.mkIf cfg.enable {
    vars.backends.local = {
      get = "cp ${cfg.directory}/$1/$2 $out";
      set = ''
        mkdir -p ${cfg.directory}/$1
        cp -f $in ${cfg.directory}/$1/$2
      '';
      exists = "test -f ${cfg.directory}/$1/$2";
      delete = ''
        rm -f ${cfg.directory}/$1/$2
        rmdir --ignore-fail-on-non-empty ${cfg.directory}/$1 || true
      '';
      list = ''
        test -d ${cfg.directory} && cd ${cfg.directory} && find . -type f -printf "%P\n" | sed 's|/| |' || true
      '';
      generators = lib.genAttrs cfg.vars (_: { });
    };
  };
}
