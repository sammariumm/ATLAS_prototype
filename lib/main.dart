import 'dart:io';
import 'package:flutter/material.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'panels/camera_panel.dart';
import 'panels/results_panel.dart';
import 'panels/export_panel.dart';
import 'services/database_helper.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  if (Platform.isWindows || Platform.isLinux) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }

  runApp(const AtlasBcApp());
}

class AtlasBcApp extends StatelessWidget {
  const AtlasBcApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ATLAS-BC',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: const Color(0xFFF8FAFC),
        primaryColor: const Color(0xFF134E4A),
      ),
      home: const Scaffold(
        backgroundColor: Colors.black87,
        body: Center(
          child: SizedBox(
            width: 480,
            height: 800,
            child: ClipRect(child: MainLayout()),
          ),
        ),
      ),
    );
  }
}

class MainLayout extends StatefulWidget {
  const MainLayout({super.key});

  @override
  State<MainLayout> createState() => _MainLayoutState();
}

class _MainLayoutState extends State<MainLayout> {
  int _currentIndex = 0;
  int _scanCounter = 1;
  String _currentScanId = 'SCAN-0001';

  // CHANGED: a scan is now a bilateral exam. _scanData holds all four views (Left CC, Left MLO, Right CC,
  // Right MLO) once the AI has analysed them; a view that does not exist has status 'na' and no image.
  List<Map<String, dynamic>> _scanData = [];

  // CHANGED: one result per breast (null = that breast was not available) plus the overall result.
  Map<String, String>? _leftResult;
  Map<String, String>? _rightResult;
  Map<String, String>? _combinedResult;
  String _analysisNote = '';

  // Changes with every new patient so the three panels start clean (no leftover pictures, verdicts or PDFs).
  int _sessionKey = 0;

  @override
  void initState() {
    super.initState();
    _loadLastScanId();
  }

  Future<void> _loadLastScanId() async {
    try {
      final lastScanId = await DatabaseHelper.instance.getLastScanId();
      if (lastScanId != null && lastScanId.startsWith('SCAN-')) {
        final numericString = lastScanId.substring(5);
        final lastCount = int.tryParse(numericString);

        if (lastCount != null) {
          setState(() {
            _scanCounter = lastCount + 1;
            _currentScanId = 'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
          });
        }
      }
    } catch (e) {
      debugPrint('Could not load previous Scan ID: $e');
    }
  }

  void _resetSession() {
    setState(() {
      _scanData = [];
      _leftResult = null;
      _rightResult = null;
      _combinedResult = null;
      _analysisNote = '';
      _currentIndex = 0;
      _sessionKey++;

      _scanCounter++;
      _currentScanId = 'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
    });
  }

  // CHANGED: called by the camera panel once the AI has analysed the captured / imported views.
  void _handleAnalysisComplete(
    List<Map<String, dynamic>> scanData,
    Map<String, String>? leftResult,
    Map<String, String>? rightResult,
    Map<String, String>? combinedResult,
    String note,
  ) {
    setState(() {
      _scanData = scanData;
      _leftResult = leftResult;
      _rightResult = rightResult;
      _combinedResult = combinedResult;
      _analysisNote = note;
      _currentIndex = 1;
    });
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> panels = [
      CameraPanel(
        key: ValueKey('camera-$_sessionKey'),
        currentScanId: _currentScanId,
        onAnalysisComplete: _handleAnalysisComplete,
        onReset: _resetSession,
        isActive: _currentIndex == 0, // the live stream only runs while this tab is showing
      ),
      ResultsPanel(
        key: ValueKey('results-$_sessionKey'),
        scanData: _scanData,
        scanId: _currentScanId,
        leftResult: _leftResult,
        rightResult: _rightResult,
        combinedResult: _combinedResult,
        note: _analysisNote,
        onNewPatient: _resetSession,
      ),
      ExportPanel(
        key: ValueKey('export-$_sessionKey'),
        scanData: _scanData,
        scanId: _currentScanId,
        leftResult: _leftResult,
        rightResult: _rightResult,
        combinedResult: _combinedResult,
        note: _analysisNote,
        onNewPatient: _resetSession,
      ),
    ];

    return Scaffold(
      body: IndexedStack(index: _currentIndex, children: panels),
      bottomNavigationBar: SizedBox(
        height: 70,
        child: BottomNavigationBar(
          currentIndex: _currentIndex,
          onTap: (index) => setState(() => _currentIndex = index),
          selectedItemColor: const Color(0xFF0D9488),
          unselectedItemColor: const Color(0xFF94A3B8),
          iconSize: 28,
          selectedFontSize: 12,
          unselectedFontSize: 12,
          items: const [
            BottomNavigationBarItem(icon: Icon(Icons.camera_alt), label: 'Camera'),
            BottomNavigationBarItem(icon: Icon(Icons.analytics), label: 'Results'),
            BottomNavigationBarItem(icon: Icon(Icons.picture_as_pdf), label: 'Export'),
          ],
        ),
      ),
    );
  }
}
