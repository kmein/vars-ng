{ lib, ... }:
{
  vars.backends.local = let varsDir = "/tmp/vars"; in {
    get = ''
      cp ${varsDir}/$1/$2 $out
    '';
    set = ''
      mkdir -p ${varsDir}/$1
      cp -f $in ${varsDir}/$1/$2
    '';
    exists = ''
      test -e ${varsDir}/$1/$2
    '';
    delete = ''
      rm -f ${varsDir}/$1/$2
      rmdir ${varsDir}/$1 2>/dev/null || true
    '';
    list = ''
      test -d ${varsDir} && cd ${varsDir} && find . -type f -printf "%P\n" | sed 's|/| |'
    '';
    generators = lib.genAttrs [ "simple" "a" "b" ] (_: { });
  };

  vars.generators = {
    simple = {
      files.simple = { };
      script = ''
        echo simple > "$out"/simple
      '';
    };
    a = {
      files.a = { };
      script = ''
        echo a > "$out"/a
      '';
    };
    b = {
      dependencies = [ "a" ];
      files.b = { };
      script = ''
        cat "$in"/a/a > "$out"/b
        echo b >> "$out"/b
      '';
    };
  };
}
