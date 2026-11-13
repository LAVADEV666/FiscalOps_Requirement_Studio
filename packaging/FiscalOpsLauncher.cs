using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

[assembly: AssemblyTitle("FiscalOps Requirement Studio")]
[assembly: AssemblyProduct("FiscalOps Requirement Studio")]
[assembly: AssemblyVersion("8.0.1.0")]

internal static class FiscalOpsLauncher
{
    [DllImport("kernel32.dll")]
    private static extern bool SetConsoleOutputCP(uint codePage);

    private static int Main(string[] args)
    {
        SetConsoleOutputCP(65001);
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        Console.Title = "FiscalOps Requirement Studio 8.0.1";
        bool check = Array.IndexOf(args, "--check") >= 0;
        int code = 1;
        try
        {
            foreach (string arg in args)
                if (arg != "--check" && arg != "--no-browser")
                    throw new ArgumentException("Opción desconocida: " + arg);
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "python.exe");
            string entry = Path.Combine(root, "desktop_entry.py");
            if (!File.Exists(python) || !File.Exists(entry))
                throw new FileNotFoundException("Extraiga TODO el ZIP antes de abrir FiscalOps.exe. Mantenga el EXE junto a runtime y static.");
            ProcessStartInfo start = new ProcessStartInfo(python);
            start.Arguments = "-B \"" + entry + "\" " + String.Join(" ", args);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.EnvironmentVariables["PYTHONUTF8"] = "1";
            using (Process process = Process.Start(start))
            {
                process.WaitForExit();
                code = process.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("[ERROR] " + error.Message);
        }
        if (code != 0 && !check && !Console.IsInputRedirected)
        {
            Console.WriteLine("Presione una tecla para cerrar esta ventana.");
            Console.ReadKey(true);
        }
        return code;
    }
}
