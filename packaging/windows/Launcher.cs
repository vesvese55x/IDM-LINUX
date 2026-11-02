using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Reflection;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Runtime.InteropServices;
using System.Windows.Forms;
[assembly: AssemblyTitle("IDM SEMO Installer")]
[assembly: AssemblyProduct("IDM SEMO")]
[assembly: AssemblyDescription("IDM SEMO 1.0.0 Windows installer — BELGESELSEMO")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
internal static class Launcher
{
    const string ExpectedBat = "@@BAT_SHA256@@";
    static string Hash(byte[] bytes) { using (SHA256 sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
    static byte[] Resource(string name)
    {
        using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
        using (MemoryStream result = new MemoryStream())
        { if (stream == null) throw new IOException("Missing installer resource: " + name); byte[] buffer = new byte[65536]; int n; while ((n = stream.Read(buffer, 0, buffer.Length)) > 0) result.Write(buffer, 0, n); return result.ToArray(); }
    }
    static string Quote(string value) { return "\"" + value + "\""; }
    // The BAT remains the one source of truth. Interpret only its setup-source echo
    // records; never start cmd.exe, powershell.exe, a VBS relaunch or a console shell.
    static string SetupSource(byte[] bat)
    {
        string text = Encoding.UTF8.GetString(bat);
        int marker = text.IndexOf("___SEMO" + "_PAYLOAD___", StringComparison.Ordinal);
        if (marker < 0) throw new IOException("Installer payload marker missing.");
        StringBuilder source = new StringBuilder();
        Regex echo = new Regex("^>>? \\\"%SEMO_WORK%\\\\setup_gui\\.cs\\\" echo(.*)$");
        foreach (string raw in text.Substring(0, marker).Split('\n'))
        {
            Match match = echo.Match(raw.TrimEnd('\r')); if (!match.Success) continue;
            string tail = match.Groups[1].Value;
            if (tail == ".") { source.AppendLine(); continue; }
            if (!tail.StartsWith(" ", StringComparison.Ordinal)) throw new IOException("Unsupported setup echo record.");
            source.AppendLine(Regex.Replace(tail.Substring(1), "\\^(.)", "$1").Replace("%%", "%"));
        }
        if (source.Length < 200000) throw new IOException("Embedded setup source is incomplete.");
        return source.ToString();
    }
    [STAThread] static void Main()
    {
        Application.EnableVisualStyles();
        try
        {
            byte[] bat = Resource("SEMO.Installer.bat");
            if (Hash(bat) != ExpectedBat) throw new IOException("Installer integrity check failed.");
            // Keep this content-addressed cache: setup reads the BAT asynchronously.
            string cache = Path.Combine(Path.Combine(Path.GetTempPath(), "IDM-SEMO"), ExpectedBat.Substring(0, 20));
            Directory.CreateDirectory(cache);
            string batFile = Path.Combine(cache, "belgeselsemo-idm-windows-installer.bat");
            File.WriteAllBytes(batFile, bat);
            string source = Path.Combine(cache, "setup_gui.cs"), setup = Path.Combine(cache, "setup_gui.exe"), icon = Path.Combine(cache, "idm-semo.ico");
            File.WriteAllText(source, SetupSource(bat), new UTF8Encoding(false));
            File.WriteAllBytes(icon, Resource("SEMO.Icon.ico"));
            string compiler = Path.Combine(RuntimeEnvironment.GetRuntimeDirectory(), "csc.exe");
            if (!File.Exists(compiler)) throw new IOException(".NET Framework compiler not found: " + compiler);
            ProcessStartInfo build = new ProcessStartInfo(compiler, "/nologo /codepage:65001 /target:winexe /win32icon:" + Quote(icon) + " /out:" + Quote(setup) + " /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll " + Quote(source));
            build.UseShellExecute = false; build.CreateNoWindow = true; build.WindowStyle = ProcessWindowStyle.Hidden;
            build.RedirectStandardOutput = true; build.RedirectStandardError = true;
            StringBuilder log = new StringBuilder();
            using (Process process = new Process())
            {
                process.StartInfo = build;
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if(e.Data != null) lock(log) log.AppendLine(e.Data); };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if(e.Data != null) lock(log) log.AppendLine(e.Data); };
                process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
                if (!process.WaitForExit(180000)) { try { process.Kill(); } catch { } throw new IOException("Installer compiler timed out."); }
                process.WaitForExit();
                File.WriteAllText(Path.Combine(cache, "compile.log"), log.ToString(), Encoding.UTF8);
                if (process.ExitCode != 0 || !File.Exists(setup)) throw new IOException("Installer compilation failed.\r\n" + log.ToString());
            }
            bool admin = new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
            string target = Path.Combine(Environment.GetFolderPath(admin ? Environment.SpecialFolder.ProgramFiles : Environment.SpecialFolder.LocalApplicationData), "IDM-SEMO");
            ProcessStartInfo launch = new ProcessStartInfo(setup, Quote(batFile) + " " + Quote(target) + " " + (admin ? "1" : "0") + " " + Quote(compiler));
            launch.UseShellExecute = false; launch.CreateNoWindow = true; launch.WorkingDirectory = cache;
            Process.Start(launch);
        }
        catch (Exception error)
        { MessageBox.Show("IDM SEMO setup could not start.\r\n\r\n" + error.Message, "IDM SEMO", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }
}
