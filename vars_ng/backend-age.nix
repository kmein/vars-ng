{ lib, config, pkgs, ... }:
let
  cfg = config.vars.backend-age;
  age = "${pkgs.age}/bin/age";
  recipientsArgs = lib.concatMapStringsSep " " (k: "-r '${k}'") cfg.publicKeys;
in
{
  options.vars.backend-age = {
    enable = lib.mkEnableOption "Use the age-encrypted local backend.";
    directory = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/vars-ng-age";
      description = "The directory where the age backend will store encrypted variables.";
    };
    vars = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "A list of variables to be stored in the age backend.";
    };
    publicKeys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      description = "Age public keys to encrypt to.";
    };
    identity = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Path to the age private key file for decryption.";
    };
  };

  config = lib.mkIf cfg.enable {
    vars.backends.age = {
      get = ''
        ${age} -d ${lib.optionalString (cfg.identity != "") "-i ${cfg.identity}"} -o $out ${cfg.directory}/$1/$2
      '';
      set = ''
        mkdir -p ${cfg.directory}/$1
        ${age} ${recipientsArgs} -o ${cfg.directory}/$1/$2 "$in" 2> /tmp/age-error.log
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
