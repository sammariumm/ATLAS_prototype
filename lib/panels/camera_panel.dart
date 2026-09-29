import 'package:flutter/material.dart';
import 'package:camera/camera.dart'; 
import 'package:flutter_mjpeg/flutter_mjpeg.dart'; 
import 'dart:io';

class CameraPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String? currentScanId;
  final Function(XFile imagePath, String side, String view, Map<String, String> aiResult) onImageCaptured;
  final VoidCallback onReset;

  const CameraPanel({
    super.key,
    required this.scanData,
    required this.currentScanId,
    required this.onImageCaptured,
    required this.onReset,
  });

  @override
  State<CameraPanel> createState() => _CameraPanelState();
}

class _CameraPanelState extends State<CameraPanel> {
  bool _isConfigured = false;
  String? _selectedSide;
  String? _selectedView;
  bool _isProcessing = false;
  String? _lastCapturedPath;

  void _cancelConfig() {
    setState(() {
      _isConfigured = false;
      _selectedSide = null;
      _selectedView = null;
      _isProcessing = false;
    });
  }

  Future<void> _executeCapture() async {
    if (_selectedSide == null || _selectedView == null) return;
    
    // 1. Setting this to true removes the Mjpeg widget from the UI.
    // This drops the HTTP connection, causing the Python server to safely release the camera.
    setState(() => _isProcessing = true);

    try {
      // 2. Wait 1 second for the hardware to fully unlock
      await Future.delayed(const Duration(milliseconds: 1000));

      final timestamp = DateTime.now().millisecondsSinceEpoch;
      final fileName = 'scan_${_selectedSide}_${_selectedView}_$timestamp.jpg'.toLowerCase();
      final savePath = '${Directory.current.path}/$fileName';

      // 3. Execute capture (added --rotation 90 to match the preview)
      // Removed --rotation 90 to prevent the hardware transpose crash
      final result = await Process.run(
        'rpicam-still',
        ['-o', savePath, '-t', '1000', '--nopreview', '--width', '1920', '--height', '1080'],
      );

      if (result.exitCode == 0) {
        setState(() => _lastCapturedPath = savePath);

        final aiData = {
          'classification': 'BI-RADS 2',
          'confidence': '92%',
          'recommendation': 'Benign findings. Routine follow-up.',
        };

        widget.onImageCaptured(XFile(savePath), _selectedSide!, _selectedView!, aiData);
        _cancelConfig();
      } else {
        throw Exception('Camera error: ${result.stderr}');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Capture Failed: $e', style: const TextStyle(color: Colors.white)),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isProcessing = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    String? takenSide = widget.scanData.isNotEmpty
        ? widget.scanData[0]['side']
        : null;

    // Phase 1: Configuration Picker (Select Left/Right & CC/MLO)
    if (!_isConfigured) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Card(
                elevation: 2,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(20.0),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        'Configure Scan #${widget.scanData.length + 1} of 2',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF0F172A),
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 20),
                      const Text(
                        'Select Breast Side:',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF475569),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('Left')),
                              selected: _selectedSide == 'Left',
                              onSelected: takenSide == 'Left'
                                  ? null
                                  : (val) => setState(() => _selectedSide = 'Left'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedSide == 'Left'
                                    ? Colors.white
                                    : (takenSide == 'Left' ? Colors.grey : Colors.black),
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('Right')),
                              selected: _selectedSide == 'Right',
                              onSelected: takenSide == 'Right'
                                  ? null
                                  : (val) => setState(() => _selectedSide = 'Right'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedSide == 'Right'
                                    ? Colors.white
                                    : (takenSide == 'Right' ? Colors.grey : Colors.black),
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 20),
                      const Text(
                        'Select View:',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF475569),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('CC')),
                              selected: _selectedView == 'CC',
                              onSelected: (val) => setState(() => _selectedView = 'CC'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedView == 'CC' ? Colors.white : Colors.black,
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: ChoiceChip(
                              label: const Center(child: Text('MLO')),
                              selected: _selectedView == 'MLO',
                              onSelected: (val) => setState(() => _selectedView = 'MLO'),
                              selectedColor: const Color(0xFF0D9488),
                              labelStyle: TextStyle(
                                color: _selectedView == 'MLO' ? Colors.white : Colors.black,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 32),
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF0D9488),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                        onPressed: (_selectedSide != null && _selectedView != null)
                            ? () => setState(() => _isConfigured = true)
                            : null,
                        child: const Text(
                          'Proceed to Capture',
                          style: TextStyle(color: Colors.white, fontSize: 16),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              if (widget.scanData.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 16.0),
                  child: TextButton.icon(
                    icon: const Icon(Icons.refresh, color: Colors.redAccent),
                    label: const Text(
                      'Discard Capture & Reset',
                      style: TextStyle(
                        color: Colors.redAccent,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    onPressed: widget.onReset,
                  ),
                ),
            ],
          ),
        ),
      );
    }

    // Phase 2: Active Live Camera Preview & Capture Screen
    return Stack(
      children: [
        // 1. Background Live MJPEG Stream (or loading spinner during capture)
        Positioned.fill(
          child: _isProcessing
              ? Container(
                  color: Colors.black,
                  child: const Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        CircularProgressIndicator(color: Color(0xFF14B8A6)),
                        SizedBox(height: 16),
                        Text(
                          'Capturing High-Res X-Ray...',
                          style: TextStyle(color: Colors.white, fontSize: 16),
                        ),
                      ],
                    ),
                  ),
                )
              : RotatedBox(
                  quarterTurns: 1, // Visually rotates the stream 90 degrees clockwise
                  child: Mjpeg(
                    isLive: true,
                    stream: 'http://localhost:8080',
                    fit: BoxFit.cover, 
                    error: (context, error, stackTrace) => Container(
                      color: Colors.black,
                      child: const Center(
                        child: Text(
                          'Starting Camera Stream...',
                          style: TextStyle(color: Colors.white54, fontSize: 14),
                        ),
                      ),
                    ),
                  ),
                ),
        ),

        // 2. HUD Target Label Overlay (Top)
        if (!_isProcessing)
          Positioned(
            top: 16,
            left: 16,
            right: 16,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    'Target: $_selectedSide Breast ($_selectedView)',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.bold,
                      fontSize: 13,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close, color: Colors.white),
                  style: IconButton.styleFrom(backgroundColor: Colors.black54),
                  onPressed: _cancelConfig,
                ),
              ],
            ),
          ),

        // 3. Shutter Button Overlay (Bottom)
        if (!_isProcessing)
          Align(
            alignment: Alignment.bottomCenter,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 30.0),
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF0D9488),
                  padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(30),
                  ),
                ),
                onPressed: _executeCapture,
                icon: const Icon(Icons.camera, color: Colors.white, size: 24),
                label: const Text(
                  'SNAP X-RAY IMAGE',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
