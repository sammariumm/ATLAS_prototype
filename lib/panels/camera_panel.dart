import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_mjpeg/flutter_mjpeg.dart';

/// Live preview (MJPEG) and high-resolution capture via `rpicam-still` on Raspberry Pi.
class CameraPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String? currentScanId;
  final void Function(
    String imagePath,
    String side,
    String view,
    Map<String, String> aiResult,
  ) onImageCaptured;
  final VoidCallback onReset;
  final VoidCallback onEnsureScanId;

  const CameraPanel({
    super.key,
    required this.scanData,
    required this.currentScanId,
    required this.onImageCaptured,
    required this.onReset,
    required this.onEnsureScanId,
  });

  @override
  State<CameraPanel> createState() => _CameraPanelState();
}

class _CameraPanelState extends State<CameraPanel> {
  /// MJPEG server started separately on the Pi (see README).
  static const String mjpegStreamUrl = 'http://localhost:8080';

  bool _isConfigured = false;
  String? _selectedSide;
  String? _selectedView;
  bool _isProcessing = false;

  void _cancelConfig() {
    setState(() {
      _isConfigured = false;
      _selectedSide = null;
      _selectedView = null;
      _isProcessing = false;
    });
  }

  /// Stops the MJPEG widget, waits for the sensor lock to release, then captures.
  Future<void> _executeCapture() async {
    if (_selectedSide == null || _selectedView == null) return;
    final scanId = widget.currentScanId;
    if (scanId == null) return;

    setState(() => _isProcessing = true);

    try {
      // Dropping the MJPEG connection lets the preview process release the camera.
      await Future.delayed(const Duration(milliseconds: 1000));

      final timestamp = DateTime.now().millisecondsSinceEpoch;
      final fileName =
          '${scanId}_${_selectedSide}_${_selectedView}_$timestamp.jpg'
              .toLowerCase();
      final scanDir = Directory('${Directory.current.path}/scans/$scanId');
      if (!await scanDir.exists()) {
        await scanDir.create(recursive: true);
      }
      final savePath = '${scanDir.path}/$fileName';

      final result = await Process.run('rpicam-still', [
        '-o',
        savePath,
        '-t',
        '1000',
        '--nopreview',
        '--width',
        '1920',
        '--height',
        '1080',
      ]);

      if (result.exitCode != 0) {
        throw Exception('Camera error: ${result.stderr}');
      }

      // Placeholder AI labels until the edge model is wired in.
      final aiData = <String, String>{
        'classification': 'BI-RADS 2',
        'confidence': '92%',
        'recommendation': 'Benign findings. Routine follow-up.',
      };

      widget.onImageCaptured(
        savePath,
        _selectedSide!,
        _selectedView!,
        aiData,
      );
      _cancelConfig();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Capture failed: $e',
              style: const TextStyle(color: Colors.white),
            ),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isProcessing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final String? takenSide = widget.scanData.isNotEmpty
        ? widget.scanData[0]['side'] as String?
        : null;

    if (!_isConfigured) {
      return _ConfigurationPhase(
        scanCount: widget.scanData.length,
        takenSide: takenSide,
        selectedSide: _selectedSide,
        selectedView: _selectedView,
        onSideSelected: (s) => setState(() => _selectedSide = s),
        onViewSelected: (v) => setState(() => _selectedView = v),
        onProceed: () {
          widget.onEnsureScanId();
          setState(() => _isConfigured = true);
        },
        onReset: widget.onReset,
        showReset: widget.scanData.isNotEmpty,
      );
    }

    return Stack(
      children: [
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
                          'Capturing high-resolution image…',
                          style: TextStyle(color: Colors.white, fontSize: 16),
                        ),
                      ],
                    ),
                  ),
                )
              : RotatedBox(
                  quarterTurns: 1,
                  child: Mjpeg(
                    isLive: true,
                    stream: mjpegStreamUrl,
                    fit: BoxFit.cover,
                    error: (context, error, stackTrace) => Container(
                      color: Colors.black,
                      child: const Center(
                        child: Text(
                          'Waiting for MJPEG stream on :8080…',
                          style: TextStyle(color: Colors.white54, fontSize: 14),
                        ),
                      ),
                    ),
                  ),
                ),
        ),
        if (!_isProcessing)
          Positioned(
            top: 16,
            left: 16,
            right: 16,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    'Target: $_selectedSide ($_selectedView)',
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
        if (!_isProcessing)
          Align(
            alignment: Alignment.bottomCenter,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 30),
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF0D9488),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(30),
                  ),
                ),
                onPressed: _executeCapture,
                icon: const Icon(Icons.camera, color: Colors.white, size: 24),
                label: const Text(
                  'SNAP IMAGE',
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

class _ConfigurationPhase extends StatelessWidget {
  const _ConfigurationPhase({
    required this.scanCount,
    required this.takenSide,
    required this.selectedSide,
    required this.selectedView,
    required this.onSideSelected,
    required this.onViewSelected,
    required this.onProceed,
    required this.onReset,
    required this.showReset,
  });

  final int scanCount;
  final String? takenSide;
  final String? selectedSide;
  final String? selectedView;
  final ValueChanged<String> onSideSelected;
  final ValueChanged<String> onViewSelected;
  final VoidCallback onProceed;
  final VoidCallback onReset;
  final bool showReset;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Card(
              elevation: 2,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Configure scan #${scanCount + 1} of 2',
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF0F172A),
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 20),
                    const Text(
                      'Select breast side',
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
                            selected: selectedSide == 'Left',
                            onSelected: takenSide == 'Left'
                                ? null
                                : (_) => onSideSelected('Left'),
                            selectedColor: const Color(0xFF0D9488),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ChoiceChip(
                            label: const Center(child: Text('Right')),
                            selected: selectedSide == 'Right',
                            onSelected: takenSide == 'Right'
                                ? null
                                : (_) => onSideSelected('Right'),
                            selectedColor: const Color(0xFF0D9488),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    const Text(
                      'Select view',
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
                            selected: selectedView == 'CC',
                            onSelected: (_) => onViewSelected('CC'),
                            selectedColor: const Color(0xFF0D9488),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ChoiceChip(
                            label: const Center(child: Text('MLO')),
                            selected: selectedView == 'MLO',
                            onSelected: (_) => onViewSelected('MLO'),
                            selectedColor: const Color(0xFF0D9488),
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
                      onPressed: (selectedSide != null && selectedView != null)
                          ? onProceed
                          : null,
                      child: const Text(
                        'Proceed to capture',
                        style: TextStyle(color: Colors.white, fontSize: 16),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (showReset)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: TextButton.icon(
                  icon: const Icon(Icons.refresh, color: Colors.redAccent),
                  label: const Text(
                    'Discard capture & reset',
                    style: TextStyle(
                      color: Colors.redAccent,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  onPressed: onReset,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
