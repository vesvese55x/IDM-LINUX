using System;
using System.Reflection;
using Semox;
internal static class RouteRegression
{
    static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
    static int Main()
    {
        try
        {
            string direct = "https://download123.mediafire.com/x/Fire+Shader.blend?a=1&amp;b=2";
            string result = Engines.ParseMediafireDownload("<a class='input' href='" + direct + "' id='downloadButton'>Download</a>");
            Check(result.EndsWith("a=1&b=2"), "HTML entities lost");
            Check(Engines.IsMediafireUrl(result), "MediaFire URL not recognized");
            Check(!Engines.IsMediafireUrl("https://mediafire.com.evil.test/x"), "Host boundary regression");
            bool refused = false;
            try { Engines.ParseMediafireDownload("<a id='downloadButton' href='https://evil.test/file.exe'>x</a>"); } catch { refused = true; }
            Check(refused, "Untrusted download link accepted");
            refused = false;
            try { Engines.ParseMediafireDownload("<p>CAPTCHA required</p>"); } catch { refused = true; }
            Check(refused, "Challenge page was treated as a download");
            Check(!Engines.IdmSendUrl("blob:https://arena.ai/object-id", null, null), "Native IDM cannot resolve browser-local Blob URLs");
            MethodInfo isVideo = typeof(OverviewPage).GetMethod("IsVideoSite", BindingFlags.NonPublic | BindingFlags.Static);
            Check(!(bool)isVideo.Invoke(null, new object[] { "https://www.mediafire.com/file/id/youtube.com.blend/file" }), "MediaFire misclassified as video");
            Check((bool)isVideo.Invoke(null, new object[] { "https://www.youtube.com/watch?v=abc" }), "YouTube routing lost");
            Check((bool)isVideo.Invoke(null, new object[] { "https://b23.tv/abc" }), "Bilibili short-link routing lost");
            Console.WriteLine("WINDOWS_SOURCE_ROUTE_REGRESSIONS_PASS");
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
}
