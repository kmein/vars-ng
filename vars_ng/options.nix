{
  lib,
  config,
  pkgs,
  ...
}:
{
  options.assertions = lib.mkOption {
    type = lib.types.listOf lib.types.unspecified;
    internal = true;
    default = [ ];
    description = "Dummy assertions option to satisfy evalModules";
  };

  options.vars = {
    settings = {
      fileModule = lib.mkOption {
        type = lib.types.deferredModule;
        internal = true;
        description = ''
          A module to be imported in every vars.files.<name> submodule.
          Used by backends to define the `path` attribute.

          Takes the file as an argument and returns maybe an attrset which should at least contain the `path` attribute.
          Can be used to set other file attributes as well, like `value`.
        '';
        default = { };
      };
    };
    backends = lib.mkOption {
      description = ''
        A set of backends that handle storing and retrieving generated files.
      '';
      default = { };
      type = lib.types.attrsOf (
        lib.types.submodule ({ name, config, ... }: {
          options = {
            name = lib.mkOption {
              type = lib.types.str;
              description = "The name of the backend.";
              readOnly = true;
              default = name;
            };
            get = lib.mkOption {
              type = lib.types.lines;
              description = ''
                A script snippet to retrieve a file. 
                Should take arguments or environment variables pointing to the required metadata.
              '';
              default = "";
            };
            set = lib.mkOption {
              type = lib.types.lines;
              description = ''
                A script snippet to store a generated file.
                Should take arguments or environment variables pointing to the output file and its metadata.
              '';
              default = "";
            };
            exists = lib.mkOption {
              type = lib.types.lines;
              description = ''
                A script snippet to check if a generated file exists in this backend.
                Should exit with 0 if it exists, and non-zero otherwise.
              '';
              default = "";
            };
            delete = lib.mkOption {
              type = lib.types.nullOr lib.types.lines;
              description = ''
                A script snippet to delete a generated file.
                Takes arguments: $1=generator_name, $2=file_name.
                Required if this backend is to support garbage collection.
              '';
              default = null;
            };
            list = lib.mkOption {
              type = lib.types.nullOr lib.types.lines;
              description = ''
                A script snippet to list all files managed by this backend.
                Should output space-separated or newline-separated pairs of:
                generator_name file_name
                Required if this backend is to support garbage collection.
              '';
              default = null;
            };
            generators = lib.mkOption {
              type = lib.types.attrsOf (lib.types.submodule { });
              description = ''
                Generators handled by this backend.
                Keys are generator names. The value is an empty attrset for now.
              '';
              default = { };
            };
          };
        })
      );
    };

    generators = lib.mkOption {
      description = ''
        A set of generators that can be used to generate files.
        Generators are scripts that produce files based on the values of other generators and user input.
        Each generator is expected to produce a set of files under a directory.
      '';
      default = { };
      type = lib.types.attrsOf (
        lib.types.submodule (generator: {
          options = {
            name = lib.mkOption {
              type = lib.types.strMatching "[a-zA-Z0-9:_\\.-]*";
              description = ''
                The name of the generator.
                This name will be used to refer to the generator in other generators.
              '';
              readOnly = true;
              default = generator.config._module.args.name;
              defaultText = "Name of the generator";
            };

            dependencies = lib.mkOption {
              description = ''
                A list of other generators that this generator depends on.
                The output values of these generators will be available to the generator script as files.
                For example, the file 'file1' of a dependency named 'dep1' will be available via $in/dep1/file1.
              '';
              type = lib.types.listOf (lib.types.strMatching "[a-zA-Z0-9:_\\.-]*");
              default = [ ];
            };
            files = lib.mkOption {
              description = ''
                A set of files to generate.
                The generator 'script' is expected to produce exactly these files under $out.
              '';
              defaultText = "attrs of files";
              type = lib.types.attrsOf (
                lib.types.submodule (file: {
                  imports = [
                    config.vars.settings.fileModule
                  ];
                  options = {
                    name = lib.mkOption {
                      type = lib.types.strMatching "[a-zA-Z0-9:_\\.-]*";
                      description = ''
                        name of the generated file
                      '';
                      readOnly = true;
                      default = file.config._module.args.name;
                      defaultText = "Name of the file";
                    };
                    generator = lib.mkOption {
                      description = ''
                        The generator that produces the file.
                        This is the name of another generator.
                      '';
                      type = lib.types.strMatching "[a-zA-Z0-9:_\\.-]*";
                      readOnly = true;
                      internal = true;
                      default = generator.config._module.args.name;
                      defaultText = "Name of the generator";
                    };
                    owner = lib.mkOption {
                      description = "The user name or id that will own the file.";
                      type = lib.types.str;
                      default = "root";
                    };
                    group = lib.mkOption {
                      description = "The group name or id that will own the file.";
                      type = lib.types.str;
                      default = "root";
                    };
                    mode = lib.mkOption {
                      description = "The unix file mode of the file. Must be a 4-digit octal number.";
                      type = lib.types.strMatching "^[0-7]{4}$";
                      default = if file.config.group == "root" then "0400" else "0440";
                    };
                    deploy = lib.mkOption {
                      description = ''
                        Whether the file should be deployed to the target machine.

                        Disable this if the generated file is only used as an input to other generators.
                      '';
                      type = lib.types.bool;
                      default = true;
                    };
                    secret = lib.mkOption {
                      description = ''
                        Whether the file should be treated as a secret.
                      '';
                      type = lib.types.bool;
                      default = true;
                    };
                    path = lib.mkOption {
                      description = ''
                        The path to the file containing the content of the generated value.
                        This will be set automatically
                      '';
                      type = lib.types.nullOr lib.types.str;
                      default = null;
                    };
                  };
                })
              );
            };
            prompts = lib.mkOption {
              description = ''
                A set of prompts to ask the user for values.
                Prompts are available to the generator script as files.
                For example, a prompt named 'prompt1' will be available via $prompts/prompt1
              '';
              default = { };
              type = lib.types.attrsOf (
                lib.types.submodule (prompt: {
                  options = {
                    name = lib.mkOption {
                      description = ''
                        The name of the prompt.
                        This name will be used to refer to the prompt in the generator script.
                      '';
                      type = lib.types.strMatching "[a-zA-Z0-9:_\\.-]*";
                      default = prompt.config._module.args.name;
                      defaultText = "Name of the prompt";
                    };
                    description = lib.mkOption {
                      description = ''
                        The description of the prompted value
                      '';
                      type = lib.types.str;
                      example = "SSH private key";
                      default = prompt.config._module.args.name;
                      defaultText = "Name of the prompt";
                    };
                    type = lib.mkOption {
                      description = ''
                        The input type of the prompt.
                        The following types are available:
                          - hidden: A hidden text (e.g. password)
                          - line: A single line of text
                          - multiline: A multiline text
                      '';
                      type = lib.types.enum [
                        "hidden"
                        "line"
                        "multiline"
                      ];
                      default = "line";
                    };
                  };
                })
              );
            };
            runtimeInputs = lib.mkOption {
              description = ''
                A list of packages that the generator script requires.
                These packages will be available in the PATH when the script is run.
              '';
              type = lib.types.listOf lib.types.package;
              default = [ pkgs.coreutils ];
            };
            script = lib.mkOption {
              description = ''
                The script to run to generate the files.
                The script will be run with the following environment variables:
                  - $in: The directory containing the output values of all declared dependencies
                  - $out: The output directory to put the generated files
                  - $prompts: The directory containing the prompted values as files
                The script should produce the files specified in the 'files' attribute under $out.
              '';
              type = lib.types.either lib.types.str lib.types.path;
              default = "";
            };
            runner = lib.mkOption {
              description = ''
                Bash script that wraps `script` with a curl prelude (fetches
                declared dependencies over $VARS_SOCKET) and postlude
                (uploads generated files back). Composed entirely in Nix
                from `runtimeInputs`, `dependencies`, `files`, and `script` —
                the orchestrator just writes this string to a temp file and
                runs it. Lazy: never forced for skipped generators.
              '';
              type = lib.types.lines;
              internal = true;
              readOnly = true;
              default =
                let
                  genName = generator.config._module.args.name;
                  binPath = lib.makeBinPath ([ pkgs.curl pkgs.coreutils ] ++ generator.config.runtimeInputs);
                  fetchDeps = lib.concatMapStringsSep "\n" (depName:
                    let
                      depFiles = lib.attrValues config.vars.generators.${depName}.files;
                    in
                    ''mkdir -p "$in/${depName}"'' + "\n" + lib.concatMapStringsSep "\n" (f: ''
                      curl "''${curl_args[@]}" "http://localhost/${depName}/${f.name}" -o "$in/${depName}/${f.name}"
                    '') depFiles
                  ) generator.config.dependencies;
                  uploadFiles = lib.concatMapStringsSep "\n" (f: ''
                    curl "''${curl_args[@]}" -X POST --data-binary @"$out/${f.name}" "http://localhost/${genName}/${f.name}"
                  '') (lib.attrValues generator.config.files);
                in
                ''
                  #!${pkgs.runtimeShell}
                  set -euo pipefail
                  umask 077
                  export PATH=${binPath}:''${PATH:-}
                  : "''${VARS_TOKEN:?VARS_TOKEN must be set}"
                  : "''${VARS_SOCKET:?VARS_SOCKET must be set}"
                  curl_args=( --fail -sS --unix-socket "$VARS_SOCKET" -H "Authorization: Bearer $VARS_TOKEN" )

                  in=$(mktemp -d)
                  out=$(mktemp -d)
                  export in out
                  trap 'rm -rf "$in" "$out"' EXIT

                  ${fetchDeps}

                  (
                    ${generator.config.script}
                  )

                  ${uploadFiles}
                '';
              defaultText = "Nix-composed bash script wrapping the generator";
            };
          };
        })
      );
    };
  };

  config = {
    assertions =
      let
        allGenNames = builtins.attrNames config.vars.generators;

        backendsForGen = genName:
          builtins.filter (
            backendName: config.vars.backends.${backendName}.generators ? ${genName}
          ) (builtins.attrNames config.vars.backends);

        validateGen = genName:
          let
            backends = backendsForGen genName;
          in
          {
            assertion = builtins.length backends == 1;
            message = "Generator '${genName}' must have exactly one backend assigned. Found ${toString (builtins.length backends)}.";
          };
      in
      map validateGen allGenNames;
  };
}
