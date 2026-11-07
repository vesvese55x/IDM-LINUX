#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdio.h>
#include <wchar.h>
static const WCHAR letters[]={0x00c7,0x011e,0x0130,0x00d6,0x015e,0x00dc,0x00e7,0x011f,0x0131,0x00f6,0x015f,0x00fc};
static int owners=0,missing_total=0;
static void hextext(const WCHAR *s){char b[8192];int n=WideCharToMultiByte(CP_UTF8,0,s,-1,b,sizeof(b),NULL,NULL);for(int i=0;i<n-1;i++)printf("%02x",(unsigned char)b[i]);}
static void fontcheck(HFONT f){HDC dc=CreateCompatibleDC(NULL);HGDIOBJ old=SelectObject(dc,f);WCHAR face[128]={0};WORD g[12];GetTextFaceW(dc,128,face);DWORD r=GetGlyphIndicesW(dc,letters,12,g,GGI_MARK_NONEXISTING_GLYPHS);int miss=0;for(int i=0;i<12;i++)if(g[i]==0xffff)miss++;if(r==GDI_ERROR)miss=12;printf("FONT\t");hextext(face);printf("\t%d\n",miss);missing_total+=miss;SelectObject(dc,old);DeleteDC(dc);}
static BOOL CALLBACK child(HWND w,LPARAM lp){WCHAR text[2048]={0};GetWindowTextW(w,text,2048);if(text[0]){printf("TEXT\t");hextext(text);printf("\n");}HFONT f=(HFONT)SendMessageW(w,WM_GETFONT,0,0);int uses_tr=0;for(int i=0;i<12;i++)if(wcschr(text,letters[i]))uses_tr=1;if(f&&uses_tr)fontcheck(f);return TRUE;}
static void menucheck(HMENU menu,int depth){if(!menu||depth>8)return;int n=GetMenuItemCount(menu);for(int i=0;i<n;i++){WCHAR b[1024]={0};GetMenuStringW(menu,i,b,1024,MF_BYPOSITION);if(b[0]){printf("MENU\t");hextext(b);printf("\n");}HMENU sub=GetSubMenu(menu,i);if(sub)menucheck(sub,depth+1);}}
static BOOL CALLBACK top(HWND w,LPARAM lp){if(!IsWindowVisible(w))return TRUE;WCHAR title[2048]={0};GetWindowTextW(w,title,2048);if(wcsstr(title,L"Internet Download Manager")||wcsstr(title,L"İndirme")||wcsstr(title,L"IDM")){owners++;printf("WINDOW\t");hextext(title);printf("\n");child(w,0);EnumChildWindows(w,child,0);menucheck(GetMenu(w),0);}return TRUE;}
int main(){SetConsoleOutputCP(CP_UTF8);printf("ACP\t%u\n",GetACP());HFONT f=CreateFontW(-16,0,0,0,400,0,0,0,TURKISH_CHARSET,0,0,0,0,L"Tahoma");fontcheck(f);DeleteObject(f);EnumWindows(top,0);printf("RESULT\t%d\t%d\n",owners,missing_total);return missing_total?2:0;}
