using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Microsoft.Win32;

namespace BlackjackPilot
{
    class Program
    {
        const int PORT = 8765;
        const string HOST = "127.0.0.1";
        const string HOST_NAME = "com.blackjackpilot.host";

        static void Main(string[] args)
        {
            if (args.Length > 0 && args[0] == "--register")
            {
                RegisterHostAndProtocol();
                return;
            }

            // Chrome native messaging loop
            try
            {
                using (var stdin = Console.OpenStandardInput())
                using (var stdout = Console.OpenStandardOutput())
                {
                    while (true)
                    {
                        byte[] lenBytes = new byte[4];
                        int read = stdin.Read(lenBytes, 0, 4);
                        if (read < 4) break;

                        int msgLen = BitConverter.ToInt32(lenBytes, 0);
                        if (msgLen <= 0 || msgLen > 10 * 1024 * 1024) break;

                        byte[] buffer = new byte[msgLen];
                        int totalRead = 0;
                        while (totalRead < msgLen)
                        {
                            int r = stdin.Read(buffer, totalRead, msgLen - totalRead);
                            if (r <= 0) break;
                            totalRead += r;
                        }
                        if (totalRead < msgLen) break;

                        string jsonStr = Encoding.UTF8.GetString(buffer);
                        string responseJson = HandleMessage(jsonStr);

                        byte[] respBytes = Encoding.UTF8.GetBytes(responseJson);
                        byte[] respLenBytes = BitConverter.GetBytes(respBytes.Length);
                        stdout.Write(respLenBytes, 0, 4);
                        stdout.Write(respBytes, 0, respBytes.Length);
                        stdout.Flush();
                    }
                }
            }
            catch (Exception ex)
            {
                try
                {
                    File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "host_error.log"),
                        DateTime.Now + " - " + ex.ToString() + Environment.NewLine);
                }
                catch { }
            }
        }

        static string HandleMessage(string json)
        {
            if (json.Contains("\"start_server\""))
            {
                return StartServer();
            }
            else if (json.Contains("\"get_status\""))
            {
                bool running = IsServerRunning();
                return string.Format("{{\"status\":\"{0}\",\"running\":{1},\"port\":{2}}}",
                    running ? "running" : "stopped", running ? "true" : "false", PORT);
            }
            return "{\"status\":\"ok\"}";
        }

        static bool IsServerRunning()
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var result = client.BeginConnect(HOST, PORT, null, null);
                    bool success = result.AsyncWaitHandle.WaitOne(400);
                    if (!success) return false;
                    client.EndConnect(result);
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        static string StartServer()
        {
            if (IsServerRunning())
            {
                return string.Format("{{\"status\":\"already_running\",\"port\":{0}}}", PORT);
            }

            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string rootDir = Path.GetFullPath(Path.Combine(baseDir, ".."));

            string[] candidates = new string[]
            {
                Path.Combine(baseDir, "BlackjackPilotServer.exe"),
                Path.Combine(rootDir, "BlackjackPilotServer.exe"),
                Path.Combine(rootDir, "dist", "BlackjackPilotServer", "BlackjackPilotServer.exe"),
                Path.Combine(baseDir, "Start-Blackjack-Server.bat"),
                Path.Combine(rootDir, "Start-Blackjack-Server.bat"),
                Path.Combine(rootDir, "start_server.bat")
            };

            string targetPath = null;
            foreach (var cand in candidates)
            {
                if (File.Exists(cand))
                {
                    targetPath = cand;
                    break;
                }
            }

            try
            {
                if (targetPath != null)
                {
                    var psi = new ProcessStartInfo();
                    psi.FileName = targetPath;
                    psi.WorkingDirectory = Path.GetDirectoryName(targetPath);
                    psi.UseShellExecute = true;
                    Process.Start(psi);
                }
                else
                {
                    // Fallback to python server.py
                    string serverPy = Path.Combine(rootDir, "server.py");
                    var psi = new ProcessStartInfo();
                    psi.FileName = "python";
                    psi.Arguments = "-u \"" + serverPy + "\"";
                    psi.WorkingDirectory = rootDir;
                    psi.UseShellExecute = true;
                    Process.Start(psi);
                }

                // Poll for port
                for (int i = 0; i < 30; i++)
                {
                    Thread.Sleep(100);
                    if (IsServerRunning())
                    {
                        return string.Format("{{\"status\":\"started\",\"port\":{0}}}", PORT);
                    }
                }

                return string.Format("{{\"status\":\"starting\",\"port\":{0}}}", PORT);
            }
            catch (Exception ex)
            {
                return string.Format("{{\"status\":\"error\",\"error\":\"{0}\"}}", ex.Message.Replace("\"", "'"));
            }
        }

        public static void RegisterHostAndProtocol()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string rootDir = Path.GetFullPath(Path.Combine(baseDir, ".."));
            string manifestPath = Path.Combine(baseDir, HOST_NAME + ".json");

            // 1. Update manifest JSON path
            string exePath = Path.Combine(baseDir, "BlackjackHost.exe");
            string manifestContent = "{\n" +
                "  \"name\": \"" + HOST_NAME + "\",\n" +
                "  \"description\": \"Blackjack Pilot Native Messaging Host\",\n" +
                "  \"path\": \"" + exePath.Replace("\\", "\\\\") + "\",\n" +
                "  \"type\": \"stdio\",\n" +
                "  \"allowed_origins\": [\n" +
                "    \"chrome-extension://podfclammipadjiimlcodaobphalfhak/\"\n" +
                "  ]\n" +
                "}";
            File.WriteAllText(manifestPath, manifestContent);

            // 2. Register Chrome Native Messaging Host
            try
            {
                using (var key = Registry.CurrentUser.CreateSubKey(@"Software\Google\Chrome\NativeMessagingHosts\" + HOST_NAME))
                {
                    if (key != null) key.SetValue("", manifestPath);
                }
                Console.WriteLine("[OK] Registered Chrome Native Messaging Host");
            }
            catch (Exception ex) { Console.WriteLine("Chrome reg error: " + ex.Message); }

            // 3. Register Edge Native Messaging Host
            try
            {
                using (var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Edge\NativeMessagingHosts\" + HOST_NAME))
                {
                    if (key != null) key.SetValue("", manifestPath);
                }
                Console.WriteLine("[OK] Registered Edge Native Messaging Host");
            }
            catch (Exception ex) { Console.WriteLine("Edge reg error: " + ex.Message); }

            // 4. Register blackjack-pilot:// URI scheme
            try
            {
                string serverExe = Path.Combine(rootDir, "dist", "BlackjackPilotServer", "BlackjackPilotServer.exe");
                if (!File.Exists(serverExe)) serverExe = Path.Combine(baseDir, "BlackjackPilotServer.exe");
                if (!File.Exists(serverExe)) serverExe = Path.Combine(rootDir, "BlackjackPilotServer.exe");

                using (var protoKey = Registry.CurrentUser.CreateSubKey(@"Software\Classes\blackjack-pilot"))
                {
                    if (protoKey != null)
                    {
                        protoKey.SetValue("", "URL:Blackjack Pilot Protocol");
                        protoKey.SetValue("URL Protocol", "");
                        using (var cmdKey = protoKey.CreateSubKey(@"shell\open\command"))
                        {
                            if (cmdKey != null)
                            {
                                cmdKey.SetValue("", "\"" + serverExe + "\" \"%1\"");
                            }
                        }
                    }
                }
                Console.WriteLine("[OK] Registered blackjack-pilot:// protocol handler");
            }
            catch (Exception ex) { Console.WriteLine("Protocol reg error: " + ex.Message); }
        }
    }
}

